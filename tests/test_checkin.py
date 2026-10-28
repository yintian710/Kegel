import concurrent.futures
import http.client
import hashlib
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
import credits
from unittest.mock import patch

import app


class QuietHandler(app.AppHandler):
    def log_message(self, *_args):
        pass


class CheckinBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.CheckinServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.secondary_secret = '二级校验"&测试'
        salt = "0123456789abcdef0123456789abcdef"
        digest = hashlib.pbkdf2_hmac("sha256", cls.secondary_secret.encode("utf-8"), bytes.fromhex(salt), 600000).hex()
        cls.secondary_hash = f"pbkdf2_sha256$600000${salt}${digest}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = patch.multiple(app, DB_PATH=Path(self.temp.name) / "test.db", ADMIN_TOKEN="test-admin", TRIGGER_TOKEN="test-trigger")
        self.config.start()
        self.addCleanup(self.config.stop)
        self.environment = patch.dict(os.environ, {"LDC_DONATION_ENABLED": "false", "LDC_CLIENT_ID": "", "LDC_CLIENT_SECRET": "",
                                                   "LINUXDO_CLIENT_ID": "", "LINUXDO_CLIENT_SECRET": "",
                                                   "ADMIN_POINTS_PASSWORD_HASH": self.secondary_hash,
                                                   "PAYMENT_LOG_PATH": str(Path(self.temp.name) / "payments.jsonl")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        app.init_db()
        self.now = 1792972800.0  # Asia/Shanghai 2026-10-26 08:00.
        self.clock = patch.object(app.time, "time", return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.quota_config = patch.object(app, "DAILY_LDC_LIMIT", 800)
        self.quota_config.start()
        self.addCleanup(self.quota_config.stop)
        self.request("/api/admin/settings", {"deadline": "22:00", "min_step_seconds": 1}, admin=True)

    def request(self, path, body=None, user=None, admin=False, headers=None):
        request_headers = {"Content-Type": "application/json"}
        if user is not None:
            token = app.sign_payload({"purpose": "session", "id": str(user), "username": f"user{user}", "exp": self.now + 86400 * 7})
            request_headers["Cookie"] = f"linuxdo_session={token}"
        if admin:
            request_headers["X-Admin-Token"] = "test-admin"
            request_headers["X-Secondary-Password"] = urllib.parse.quote(self.secondary_secret)
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        try:
            connection.request("GET" if body is None else "POST", path, body=json.dumps(body) if body is not None else None, headers=request_headers)
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if response.getheader("Content-Type", "").startswith("application/json") else body.decode()
        finally:
            connection.close()

    def open(self):
        code, _ = self.request("/api/admin/open", {}, admin=True)
        self.assertEqual(code, 200)

    def prepare(self, user):
        code, result = self.request("/api/session/start", {}, user=user)
        self.assertEqual(code, 200, result)
        session = result["session"]
        while session["step"] < 2:
            app.time.time.return_value = app.time.time() + 2
            code, result = self.request("/api/session/step", {"token": session["token"]}, user=user)
            self.assertEqual(code, 200, result)
            session = result["session"]
        return session

    def complete(self, user):
        session = self.prepare(user)
        if session["step"] == 3:
            return self.request("/api/status", user=user)[1]["entry"]
        app.time.time.return_value = app.time.time() + 2
        code, result = self.request("/api/session/complete", {"token": session["token"]}, user=user)
        self.assertEqual(code, 200, result)
        return result["entry"]

    def auth_response(self, path, cookie=""):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        try:
            connection.request("GET", path, headers={"Cookie": cookie} if cookie else {})
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def auto_round(self, user, repetitions, interval=2):
        code, result = self.request("/api/session/start", {
            "mode": "auto", "repetitions": repetitions, "interval_seconds": interval,
        }, user=user)
        self.assertEqual(code, 200, result)
        session = result["session"]
        for _ in range(repetitions - 1):
            app.time.time.return_value += interval
            code, result = self.request("/api/session/step", {"token": session["token"]}, user=user)
            self.assertEqual(code, 200, result)
            session = result["session"]
        app.time.time.return_value += interval
        code, result = self.request("/api/session/complete", {"token": session["token"]}, user=user)
        self.assertEqual(code, 200, result)
        self.assertTrue(result["session"]["completed"])
        return result

    def test_auto_round_counts_repeat_without_duplicate_daily_rewards(self):
        self.open()
        first = self.auto_round(1, 20)
        self.assertIsNotNone(first["entry"])
        self.auto_round(1, 1, 5)
        self.assertEqual(self.request("/api/claim", {}, user=1)[0], 200)
        self.auto_round(2, 3)
        state = self.request("/api/status", user=1)[1]
        self.assertEqual([(row["username"], row["count"]) for row in state["practice_leaderboard"]],
                         [("user1", 21), ("user2", 3)])
        self.assertEqual(state["total"], 2)
        self.assertEqual(state["entry"]["rank"], 1)
        self.assertEqual(state["wallet"]["balance"], 1000)
        self.assertIsNone(state["review"])
        self.assertEqual(self.request("/api/claim", {}, user=1)[1]["wallet"]["balance"], 1000)

    def test_auto_round_cannot_complete_early_or_accept_invalid_settings(self):
        for repetitions, interval in [(0, 2), (21, 2), (True, 2), (2, 1), (2, 6), (2, 2.5)]:
            self.assertEqual(self.request("/api/session/start", {
                "mode": "auto", "repetitions": repetitions, "interval_seconds": interval,
            }, user=1)[0], 400)
        _, result = self.request("/api/session/start", {
            "mode": "auto", "repetitions": 1, "interval_seconds": 2,
        }, user=1)
        token = result["session"]["token"]
        self.assertEqual(self.request("/api/session/complete", {"token": token}, user=1)[0], 429)
        self.assertEqual(self.request("/api/status", user=1)[1]["practice_leaderboard"], [])
        app.time.time.return_value += 2
        code, result = self.request("/api/session/complete", {"token": token}, user=1)
        self.assertEqual(code, 200, result)
        self.assertIsNone(result["entry"])
        self.assertEqual(self.request("/api/status", user=1)[1]["practice_leaderboard"][0]["count"], 1)
        self.request("/api/session/complete", {"token": result["session"]["token"]}, user=1)
        self.assertEqual(self.request("/api/status", user=1)[1]["practice_leaderboard"][0]["count"], 1)

    def test_manual_practice_can_repeat_without_replacing_daily_reward(self):
        self.open()
        first = self.complete(1)
        second = self.complete(1)
        self.assertEqual(second["flow_id"], first["flow_id"])
        state = self.request("/api/status", user=1)[1]
        self.assertEqual(state["practice_leaderboard"][0]["count"], 6)
        self.assertEqual(state["total"], 1)
        self.assertEqual(self.request("/api/claim", {}, user=1)[1]["wallet"]["balance"], 1000)

    def test_configured_oauth_allows_guest_practice_and_protects_account_pages(self):
        with patch.dict(os.environ, {"LINUXDO_CLIENT_ID": "client", "LINUXDO_CLIENT_SECRET": "secret"}):
            for path, target in [("/shop", "/shop"), ("/shop.html", "/shop"), ("/donate", "/donate"), ("/donate.html", "/donate"), ("/admin", "/admin"), ("/admin.html", "/admin")]:
                code, headers, _ = self.auth_response(path)
                self.assertEqual(code, 302)
                self.assertTrue(dict(headers)["Location"].startswith("https://connect.linux.do/oauth2/authorize?"))
                state_cookie = next(value.split(";", 1)[0].split("=", 1)[1] for key, value in headers if key == "Set-Cookie")
                self.assertEqual(app.verify_payload(state_cookie)["next"], target)
            for path in ("/", "/index.html", "/practice", "/practice.html"):
                self.assertEqual(self.auth_response(path)[0], 200)
            self.assertEqual(self.request("/api/status")[0], 200)
            for path in ("/api/shop", "/api/donations"):
                self.assertEqual(self.request(path)[0], 401)
            self.assertEqual(self.request("/api/visit", {})[0], 200)
            code, result = self.request("/api/session/start", {})
            self.assertEqual(code, 200)
            self.assertFalse(result["session"]["eligible"])
            self.assertEqual(self.request("/api/claim", {})[0], 401)
            self.assertEqual(self.auth_response("/api/icon?size=32")[0], 200)
            self.assertEqual(self.request("/api/status", user=1)[0], 200)
        self.assertEqual(self.auth_response("/")[0], 200)

    def test_oauth_session_lasts_five_days_and_renews_until_expiry(self):
        saved = app.sign_payload({"purpose": "oauth", "state": "state", "next": "/shop", "exp": self.now + 600})
        with patch.object(app, "json_request", side_effect=[{"access_token": "access"}, {"id": 1, "username": "alice", "name": "Alice"}]):
            code, headers, _ = self.auth_response("/auth/linuxdo/callback?code=code&state=state", "oauth_state=" + saved)
        self.assertEqual((code, dict(headers)["Location"]), (303, "/shop"))
        session_header = next(value for key, value in headers if key == "Set-Cookie" and value.startswith("linuxdo_session="))
        self.assertIn("Max-Age=432000", session_header)
        self.assertIn("HttpOnly", session_header)
        session_cookie = session_header.split(";", 1)[0]
        self.assertEqual(app.verify_payload(session_cookie.split("=", 1)[1])["exp"], self.now + 432000)
        app.time.time.return_value = self.now + 4 * 86400
        code, headers, _ = self.auth_response("/api/status", session_cookie)
        self.assertEqual(code, 200)
        renewed_cookie = next(value.split(";", 1)[0] for key, value in headers if key == "Set-Cookie" and value.startswith("linuxdo_session="))
        renewed = app.verify_payload(renewed_cookie.split("=", 1)[1])
        self.assertEqual((renewed["id"], renewed["username"], renewed["exp"]), ("1", "alice", self.now + 9 * 86400))
        with patch.dict(os.environ, {"LINUXDO_CLIENT_ID": "client", "LINUXDO_CLIENT_SECRET": "secret"}):
            app.time.time.return_value = self.now + 6 * 86400
            self.assertEqual(self.auth_response("/", renewed_cookie)[0], 200)
            code, headers, _ = self.auth_response("/", session_cookie)
            self.assertEqual(code, 200)
            self.assertFalse(any(key == "Set-Cookie" and value.startswith("linuxdo_session=") for key, value in headers))
            code, headers, _ = self.auth_response("/auth/logout", renewed_cookie)
            session_headers = [value for key, value in headers if key == "Set-Cookie" and value.startswith("linuxdo_session=")]
            self.assertEqual(code, 303)
            self.assertEqual(len(session_headers), 1)
            self.assertIn("Max-Age=0", session_headers[0])

    def test_auth_closed_admin_and_trigger_guards(self):
        self.assertEqual(self.request("/api/admin")[0], 401)
        self.assertEqual(self.request("/api/admin/open", {})[0], 401)
        self.assertFalse(self.request("/api/session/start", {})[1]["session"]["eligible"])
        self.assertFalse(self.request("/api/session/start", {}, user=1)[1]["session"]["eligible"])
        self.assertEqual(self.request("/api/claim", {})[0], 401)
        self.assertEqual(self.request("/api/trigger/open", {})[0], 401)
        self.assertEqual(self.request("/api/trigger/open", {}, headers={"X-Trigger-Token": "test-trigger"})[0], 200)
        _, state = self.request("/api/status")
        self.assertTrue(state["is_open"])
        self.assertEqual(state["open_reason"], "trigger")
        with patch.object(app, "ADMIN_TOKEN", ""):
            self.assertEqual(self.request("/api/admin", admin=True)[0], 401)
        self.assertEqual(self.request("/api/admin/open", {}, admin=True, headers={"Origin": "https://other.example"})[0], 403)

    def test_timing_token_replay_and_daily_uniqueness(self):
        self.open()
        _, result = self.request("/api/session/start", {}, user=1)
        old_token = result["session"]["token"]
        self.assertEqual(self.request("/api/session/step", {"token": old_token}, user=1)[0], 429)
        entry = self.complete(1)
        self.assertEqual(entry["rank"], 1)
        self.assertEqual(self.request("/api/session/step", {"token": old_token}, user=1)[0], 409)
        again = self.complete(1)
        self.assertEqual(again["rank"], 1)
        state = self.request("/api/status", user=1)[1]
        self.assertEqual((state["total"], state["wallet"]["balance"]), (1, 0))
        _, result = self.request("/api/claim", {"amount": 99999999}, user=1)
        self.assertEqual(result["entry"]["reward_status"], "credited")
        self.assertEqual(result["wallet"]["balance"], 1000)
        self.assertEqual(self.request("/api/claim", {}, user=1)[1]["wallet"]["balance"], 1000)

    def test_reward_boundaries_and_configuration_snapshot(self):
        self.open()
        for prior, expected in [(9, 1000), (19, 500), (49, 100), (50, 0)]:
            with self.subTest(rank=prior + 1):
                with app.db() as connection:
                    connection.execute("DELETE FROM entries")
                    connection.execute("DELETE FROM sessions")
                    for rank in range(1, prior + 1):
                        connection.execute("INSERT INTO entries(day,user_id,username,rank,amount,completed_at,reward_status) VALUES (?,?,?,?,?,?,?)", (app.day_key(), str(rank), f"user{rank}", rank, 1000, self.now, "unclaimed"))
                entry = self.complete(999)
                self.assertEqual((entry["rank"], entry["amount"]), (prior + 1, expected))
        self.request("/api/admin/settings", {"reward_tiers": [{"through": 100, "amount": 3000}]}, admin=True)
        self.assertEqual(self.request("/api/status", user=999)[1]["entry"]["amount"], 0)
        self.assertEqual(self.request("/api/claim", {}, user=999)[1]["entry"]["reward_status"], "none")
        self.assertEqual(self.request("/api/shop", user=999)[1]["wallet"]["balance"], 0)

    def test_concurrent_completions_have_distinct_ranks(self):
        self.open()
        tokens = {user: self.prepare(user)["token"] for user in range(1, 7)}
        app.time.time.return_value = app.time.time() + 2
        def finish(user):
            code, result = self.request("/api/session/complete", {"token": tokens[user]}, user=user)
            self.assertEqual(code, 200, result)
            return result["entry"]["rank"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            ranks = list(pool.map(finish, tokens))
        self.assertEqual(sorted(ranks), [1, 2, 3, 4, 5, 6])

    def test_concurrent_claims_credit_wallet_and_ledger_once(self):
        self.open()
        self.complete(7)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.request("/api/claim", {}, user=7), range(8)))
        self.assertTrue(all(code == 200 and value["wallet"]["balance"] == 1000 for code, value in results))
        shop = self.request("/api/shop", user=7)[1]
        self.assertEqual(shop["wallet"]["balance"], 1000)
        self.assertEqual([(item["delta"], item["balance_after"]) for item in shop["ledger"]], [(1000, 1000)])
        self.assertEqual(self.request("/api/shop", user=8)[1]["ledger"], [])
        self.assertIsNone(self.request("/api/shop")[1]["wallet"])

    def test_ledger_failure_rolls_back_wallet_and_claim(self):
        self.open()
        self.complete(1)
        with app.db() as connection:
            connection.execute("CREATE TRIGGER fail_ledger BEFORE INSERT ON points_ledger BEGIN SELECT RAISE(ABORT,'forced storage failure'); END")
        self.assertEqual(self.request("/api/claim", {}, user=1)[0], 500)
        state = self.request("/api/status", user=1)[1]
        self.assertEqual((state["wallet"]["balance"], state["entry"]["reward_status"]), (0, "unclaimed"))
        self.assertEqual(self.request("/api/shop", user=1)[1]["ledger"], [])
        with app.db() as connection:
            connection.execute("DROP TRIGGER fail_ledger")
        self.assertEqual(self.request("/api/claim", {}, user=1)[1]["wallet"]["balance"], 1000)

    def test_verified_donations_rank_once_without_crediting_points(self):
        with patch.dict(os.environ, {"LDC_DONATION_ENABLED": "true", "LDC_CLIENT_ID": "merchant", "LDC_CLIENT_SECRET": "test-secret"}):
            code, created = self.request("/api/donations/create", {"amount": "3.00"}, user=1)
            self.assertEqual(code, 200, created)
            order = created["order"]
            for _ in range(2):
                code, state = self.request(f"/api/donations?donation={order['order_no']}&paid=1", user=1)
                shop = self.request("/api/shop", user=1)[1]
                self.assertEqual((shop["wallet"]["balance"], shop["ledger"], state["donation_leaderboard"]), (0, [], []))
            fields = created["payment"]["fields"]
            notify = {key: fields[key] for key in ["pid", "type", "out_trade_no", "name", "money"]}
            notify.update({"trade_no": "HTTP-TRADE-1", "trade_status": "TRADE_SUCCESS"})
            payload = "&".join(f"{key}={value}" for key, value in sorted(notify.items())) + "test-secret"
            notify["sign"] = hashlib.md5(payload.encode()).hexdigest()
            url = "/payments/ldc/notify?" + urllib.parse.urlencode(notify)
            for _ in range(2):
                self.assertEqual(self.request(url), (200, "success"))
            self.assertEqual(self.request(url + "&money=3.00"), (400, "fail"))
            state = self.request("/api/donations", user=1)[1]
            self.assertEqual(state["donation_leaderboard"][0], {"rank": 1, "username": "user1", "amount": "3.00", "count": 1})
            shop = self.request("/api/shop", user=1)[1]
            self.assertEqual((shop["wallet"]["balance"], shop["ledger"]), (0, []))
            self.assertEqual(self.request("/api/donations", user=2)[1]["donation_orders"], [])
        self.assertEqual(self.request("/api/claim", {}, user=1)[0], 409)
        records = [json.loads(line) for line in Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len([row for row in records if row["event"] == "callback.accepted"]), 2)
        rejected = next(row for row in records if row["event"] == "callback.rejected")
        self.assertEqual(rejected["reason"], "重复的通知字段")
        reply = next(row for row in records if row["event"] == "inbound.response" and row["exchange_id"] == rejected["exchange_id"])
        self.assertEqual(reply["body"], "fail")
        text = Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8")
        self.assertIn(order["order_no"], text)
        self.assertIn("HTTP-TRADE-1", text)
        self.assertNotIn(notify["sign"], text)
        self.assertNotIn("test-secret", text)

    def test_periodic_visits_require_review_then_approval(self):
        self.open()
        with app.db() as connection:
            for i in range(5, 0, -1):
                app.record_visit(connection, "1", "user1", "visitor", "127.0.0.1", "visit", self.now - i * 60)
        code, result = self.request("/api/visit", {}, user=1)
        self.assertEqual(code, 200)
        self.assertIn("固定周期", result["review"]["reason"])
        self.assertFalse(self.request("/api/session/start", {}, user=1)[1]["session"]["eligible"])
        self.assertEqual(self.request("/api/admin/review", {"user_id": "1", "approved": True}, admin=True)[0], 200)
        self.assertEqual(self.request("/api/session/start", {}, user=1)[0], 200)
        visits = self.request("/api/admin", admin=True)[1]["visits"]
        self.assertEqual(visits[0]["user_id"], "1")
        self.assertGreaterEqual(visits[0]["count"], 8)

    def test_deadline_rollover_preserves_wallet_but_resets_rank(self):
        with app.db() as connection:
            before = app.ensure_day(connection, self.now)
            self.assertIsNone(before["opened_at"])
            deadline = app.datetime.fromisoformat(before["day"] + "T22:00:00+08:00").timestamp()
            self.assertEqual(app.ensure_day(connection, deadline)["open_reason"], "deadline")
        self.complete(1)
        self.request("/api/claim", {}, user=1)
        old = self.request("/api/status", user=1)[1]
        with patch.object(app.time, "time", return_value=self.now + 86400):
            fresh = self.request("/api/status", user=1)[1]
            self.assertNotEqual(old["day"], fresh["day"])
            self.assertEqual((fresh["total"], fresh["wallet"]["balance"]), (0, 1000))
            self.assertIsNone(fresh["entry"])
            self.assertFalse(fresh["is_open"])
            self.assertEqual(fresh["quota"]["used"], "0.00")
            self.assertEqual(fresh["quota"]["remaining"], fresh["quota"]["limit"])
            self.assertEqual(self.request("/api/session/step", {"token": old["session"]["token"]}, user=1)[0], 409)
            self.open()
            self.complete(1)
            self.assertEqual(self.request("/api/claim", {}, user=1)[1]["wallet"]["balance"], 2000)
        self.assertEqual([item["balance_after"] for item in self.request("/api/shop", user=1)[1]["ledger"]], [2000, 1000])
        app.init_db()
        self.assertEqual(self.request("/api/shop", user=1)[1]["wallet"]["balance"], 2000)

    def test_invalid_rewards_are_rejected_without_partial_save(self):
        for amount in ["NaN", "Infinity", -1, 0.5, True, 100000001]:
            code, _ = self.request("/api/admin/settings", {"deadline": "21:00", "reward_tiers": [{"through": 10, "amount": amount}]}, admin=True)
            self.assertEqual(code, 400)
        self.assertEqual(self.request("/api/admin", admin=True)[1]["settings"]["deadline"], "22:00")
        self.assertEqual(self.request("/api/admin/settings", {"min_step_seconds": 0}, admin=True)[0], 400)
        self.assertEqual(self.request("/api/admin/settings", {"condition_url": "file:///etc/passwd"}, admin=True)[0], 400)
        self.assertEqual(self.request("/api/admin/settings", {"daily_ldc_limit": 900}, admin=True)[0], 400)

    def test_condition_scheduler_opens_only_for_true_condition(self):
        self.request("/api/admin/settings", {"condition_url": "http://condition.example/open"}, admin=True)
        for response in [{"open": "true"}, {"open": True}]:
            stop = threading.Event()
            def condition(*args, **kwargs):
                stop.set()
                return response
            with patch.object(app, "json_request", side_effect=condition):
                app.scheduler(stop)
            self.assertEqual(self.request("/api/status")[1]["is_open"], response["open"] is True)

    def test_checkin_rewards_do_not_consume_or_require_ldc_quota(self):
        self.open()
        self.complete(1)
        code, result = self.request("/api/claim", {}, user=1)
        self.assertEqual(code, 200)
        self.assertEqual(result["wallet"]["balance"], 1000)
        self.assertEqual(result["quota"], {"limit": "800.00", "used": "0.00", "remaining": "800.00"})
        app.DAILY_LDC_LIMIT = 0
        self.complete(2)
        code, result = self.request("/api/claim", {}, user=2)
        self.assertEqual(code, 200)
        self.assertEqual(result["wallet"]["balance"], 1000)
        self.assertEqual(result["quota"], {"limit": "0.00", "used": "0.00", "remaining": "0.00"})

    def quota_product(self, amount):
        code, result = self.request("/api/admin/products", {
            "category": "LDC", "name": f"{amount} LDC", "description": "",
            "points_price": 100, "ldc_amount": amount, "user_daily_limit": 0,
            "total_daily_limit": 0, "is_active": True,
        }, admin=True)
        self.assertEqual(code, 200, result)
        return result["product"]["id"]

    def seed_wallet(self, user):
        with app.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            credits.credit_checkin(connection, {"id": str(user), "username": f"user{user}"}, 1000, f"seed:{user}", self.now)

    def test_concurrent_redemptions_enforce_global_ldc_budget_across_products(self):
        first, second = self.quota_product("500.00"), self.quota_product("500.00")
        for user in (1, 2, 3):
            self.seed_wallet(user)
        with patch.object(app, "dispatch_ldc", return_value=("success", "trade", "")) as dispatch:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda item: self.request("/api/shop/purchase", {"product_id": item[1]}, user=item[0]), [(1, first), (2, second)]))
            self.assertEqual(sorted(code for code, _ in results), [200, 400])
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(self.request("/api/shop")[1]["quota"], {"limit": "800.00", "used": "500.00", "remaining": "300.00"})
        self.assertEqual(sum(self.request("/api/shop", user=user)[1]["wallet"]["balance"] for user in (1, 2)), 1900)
        last = self.quota_product("300.00")
        with patch.object(app, "dispatch_ldc", return_value=("success", "last", "")):
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": last}, user=3)[0], 200)
        self.assertEqual(self.request("/api/shop")[1]["quota"], {"limit": "800.00", "used": "800.00", "remaining": "0.00"})
        self.assertEqual(self.request("/api/shop/purchase", {"product_id": last}, user=3)[0], 400)

    def test_ldc_quota_exact_cents_failure_uncertainty_and_next_day(self):
        app.DAILY_LDC_LIMIT = 1
        self.seed_wallet(1)
        small, rest = self.quota_product("0.10"), self.quota_product("0.90")
        for status, expected_used, expected_balance in [("failed", "0.00", 1000), ("uncertain", "0.10", 900), ("simulated", "0.20", 800)]:
            with patch.object(app, "dispatch_ldc", return_value=(status, "trade", "error")):
                code, result = self.request("/api/shop/purchase", {"product_id": small}, user=1)
            self.assertEqual((code, result["status"]), (200, status))
            shop = self.request("/api/shop", user=1)[1]
            self.assertEqual(shop["quota"]["used"], expected_used)
            self.assertEqual(shop["wallet"]["balance"], expected_balance)
        with patch.object(app, "dispatch_ldc") as dispatch:
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": rest}, user=1)[0], 400)
            dispatch.assert_not_called()
        final = self.quota_product("0.80")
        with patch.object(app, "dispatch_ldc", return_value=("success", "trade", "")):
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": final}, user=1)[0], 200)
        self.assertEqual(self.request("/api/shop")[1]["quota"], {"limit": "1.00", "used": "1.00", "remaining": "0.00"})
        with patch.object(app.time, "time", return_value=self.now + 86400):
            self.assertEqual(self.request("/api/shop")[1]["quota"], {"limit": "1.00", "used": "0.00", "remaining": "1.00"})
        app.DAILY_LDC_LIMIT = 0
        with patch.object(app, "dispatch_ldc") as dispatch:
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": small}, user=1)[0], 400)
            dispatch.assert_not_called()

    def test_secondary_password_required_for_rewards_and_products(self):
        # 1. Update reward tiers
        tiers_payload = {"reward_tiers": [{"through": 10, "amount": 1000}]}
        # Without password
        code, err = self.request("/api/admin/settings", tiers_payload, admin=True, headers={"X-Secondary-Password": ""})
        self.assertEqual(code, 403)
        # With wrong password
        code, err = self.request("/api/admin/settings", tiers_payload, admin=True, headers={"X-Secondary-Password": "bad"})
        self.assertEqual(code, 403)
        # With correct password
        code, res = self.request("/api/admin/settings", tiers_payload, admin=True)
        self.assertEqual(code, 200)

        # 2. Add product
        prod_payload = {
            "category": "LDC", "name": "测试商品", "description": "测试",
            "points_price": 100, "ldc_amount": "1.00", "user_daily_limit": 1, "total_daily_limit": 5, "is_active": True
        }
        code, err = self.request("/api/admin/products", prod_payload, admin=True, headers={"X-Secondary-Password": ""})
        self.assertEqual(code, 403)
        code, res = self.request("/api/admin/products", prod_payload, admin=True)
        self.assertEqual(code, 200)
        pid = res["product"]["id"]

        # 3. Archive product
        code, err = self.request(f"/api/admin/products/{pid}/archive", {}, admin=True, headers={"X-Secondary-Password": "wrong"})
        self.assertEqual(code, 403)
        code, res = self.request(f"/api/admin/products/{pid}/archive", {}, admin=True)
        self.assertEqual(code, 200)

        # 4. Support ADMIN_SECONDARY_PASSWORD plaintext fallback
        with patch.dict(os.environ, {"ADMIN_POINTS_PASSWORD_HASH": "", "ADMIN_SECONDARY_PASSWORD": "plain-secondary-pass"}):
            code, _ = self.request("/api/admin/products", prod_payload, admin=True, headers={"X-Secondary-Password": "plain-secondary-pass"})
            self.assertEqual(code, 200)
            code, _ = self.request("/api/admin/products", prod_payload, admin=True, headers={"X-Secondary-Password": "wrong"})
            self.assertEqual(code, 403)

    def test_environment_budget_overrides_obsolete_database_settings(self):
        with app.db() as connection:
            connection.execute("INSERT INTO checkin_settings(key,value) VALUES ('daily_points_limit','900')")
            connection.execute("INSERT INTO checkin_settings(key,value) VALUES ('daily_ldc_limit','700')")
        app.init_db()
        with app.db() as connection:
            self.assertNotIn("daily_points_limit", app.settings(connection))
            self.assertNotIn("daily_ldc_limit", app.settings(connection))
        self.assertEqual(self.request("/api/shop")[1]["quota"]["limit"], "800.00")

    def test_each_trigger_is_recorded_and_claim_requires_qualified_intervals(self):
        self.open()
        _, result = self.request("/api/session/start", {}, user=1)
        token = result["session"]["token"]
        self.assertEqual(self.request("/api/session/complete", {"token": token}, user=1)[0], 409)
        self.assertEqual(self.request("/api/session/step", {"token": token}, user=1)[0], 429)
        for _ in range(2):
            app.time.time.return_value = app.time.time() + 2
            _, result = self.request("/api/session/step", {"token": token}, user=1)
            token = result["session"]["token"]
        self.assertEqual(self.request("/api/claim", {}, user=1)[0], 409)
        self.assertEqual(self.request("/api/session/complete", {"token": token}, user=1)[0], 429)
        app.time.time.return_value = app.time.time() + 2
        self.assertEqual(self.request("/api/session/complete", {"token": token}, user=1)[0], 200)
        with app.db() as connection:
            events = connection.execute("SELECT group_no,created_at FROM practice_triggers WHERE user_id='1' ORDER BY id").fetchall()
            self.assertEqual([row["group_no"] for row in events], [1, 2, 3])
            self.assertEqual([row["created_at"] for row in events], [self.now, self.now + 2, self.now + 4])
            connection.execute("UPDATE practice_triggers SET created_at=? WHERE user_id='1' AND group_no=2", (self.now + .5,))
        self.assertEqual(self.request("/api/claim", {}, user=1)[0], 429)
        self.assertEqual(self.request("/api/shop", user=1)[1]["wallet"]["balance"], 0)

    def test_ten_minute_boundary_resets_flow_and_keeps_old_trigger_history(self):
        self.open()
        _, result = self.request("/api/session/start", {}, user=1)
        old_token = result["session"]["token"]
        app.time.time.return_value = self.now + 600
        self.assertIsNone(self.request("/api/status", user=1)[1]["session"])
        self.assertEqual(self.request("/api/session/step", {"token": old_token}, user=1)[0], 409)
        _, result = self.request("/api/session/start", {}, user=1)
        self.assertEqual(result["session"]["step"], 0)
        token = result["session"]["token"]
        self.assertNotEqual(token, old_token)
        app.time.time.return_value = self.now + 1199
        code, result = self.request("/api/session/step", {"token": token}, user=1)
        self.assertEqual(code, 200, result)
        self.assertEqual(result["session"]["expires_in"], 600)
        app.time.time.return_value = self.now + 1799
        self.assertEqual(self.request("/api/session/step", {"token": result["session"]["token"]}, user=1)[0], 409)
        with app.db() as connection:
            rows = connection.execute("SELECT flow_id,group_no FROM practice_triggers WHERE user_id='1' ORDER BY id").fetchall()
            self.assertEqual([row["group_no"] for row in rows], [1, 1, 2])
            self.assertNotEqual(rows[0]["flow_id"], rows[1]["flow_id"])

    def test_anonymous_practice_records_three_triggers_without_ranking(self):
        cookie = app.sign_payload({"purpose": "visitor", "visitor": "anon-test", "exp": self.now + 3600})
        headers = {"Cookie": "checkin_visitor=" + cookie}
        _, result = self.request("/api/session/start", {}, headers=headers)
        self.assertFalse(result["session"]["eligible"])
        for _ in range(2):
            app.time.time.return_value = app.time.time() + 2
            _, result = self.request("/api/session/step", {"token": result["session"]["token"]}, headers=headers)
        app.time.time.return_value = app.time.time() + 2
        code, result = self.request("/api/session/complete", {"token": result["session"]["token"]}, headers=headers)
        self.assertEqual(code, 200, result)
        self.assertIsNone(result["entry"])
        self.assertEqual(self.request("/api/status", headers=headers)[1]["total"], 0)
        triggers = self.request("/api/admin", admin=True)[1]["practice_triggers"]
        self.assertEqual([item["group_no"] for item in triggers], [3, 2, 1])

    def test_admin_product_catalog_crud_and_shop_listing(self):
        code, result = self.request("/api/admin/products", {
            "category": "LDC", "name": "1.00 LDC 兑换", "description": "提肛达人专属兑换",
            "points_price": 500, "ldc_amount": "1.00", "user_daily_limit": 1, "total_daily_limit": 5, "is_active": True
        }, admin=True)
        self.assertEqual(code, 200)
        product_id = result["product"]["id"]
        self.assertEqual(result["product"]["category"], "LDC")
        self.assertEqual(result["product"]["ldc_amount"], "1.00")
        self.assertEqual(result["product"]["user_daily_limit"], 1)
        self.assertEqual(result["product"]["total_daily_limit"], 5)

        shop = self.request("/api/shop")[1]
        self.assertEqual(len(shop["products"]), 1)
        self.assertEqual(shop["products"][0]["name"], "1.00 LDC 兑换")
        self.assertEqual(shop["products"][0]["points_price"], 500)

        # Update
        self.request("/api/admin/products", {
            "id": product_id, "category": "LDC", "name": "2.00 LDC 兑换", "description": "高级达人专属",
            "points_price": 800, "ldc_amount": "2.00", "user_daily_limit": 2, "total_daily_limit": 10, "is_active": True
        }, admin=True)
        shop = self.request("/api/shop")[1]
        self.assertEqual(shop["products"][0]["name"], "2.00 LDC 兑换")
        self.assertEqual(shop["products"][0]["ldc_amount"], "2.00")
        self.assertEqual(shop["products"][0]["points_price"], 800)

        # Archive
        self.request(f"/api/admin/products/{product_id}/archive", {}, admin=True)
        self.assertEqual(self.request("/api/shop")[1]["products"], [])
        admin_state = self.request("/api/admin", admin=True)[1]
        self.assertEqual(len(admin_state["products"]), 1)
        self.assertFalse(admin_state["products"][0]["is_active"])

    def test_purchase_ldc_product_auto_delivery_and_limits(self):
        # 1. Create product with user_daily_limit=1, total_daily_limit=2
        code, res = self.request("/api/admin/products", {
            "category": "LDC", "name": "0.50 LDC", "description": "自动发货到账号",
            "points_price": 300, "ldc_amount": "0.50", "user_daily_limit": 1, "total_daily_limit": 2, "is_active": True
        }, admin=True)
        pid = res["product"]["id"]

        # 2. Give user 1 and user 2 some points via checkin
        self.open()
        self.complete(1)
        self.request("/api/claim", {}, user=1) # user1 has 1000 points
        self.complete(2)
        self.request("/api/claim", {}, user=2) # user2 has 500 points

        # 3. User 1 purchases -> simulated auto delivery
        code, purchase_res = self.request("/api/shop/purchase", {"product_id": pid}, user=1)
        self.assertEqual(code, 200, purchase_res)
        self.assertEqual(purchase_res["status"], "simulated")
        self.assertTrue(purchase_res["trade_no"].startswith("SIM-"))

        # Points deducted: 1000 - 300 = 700
        shop1 = self.request("/api/shop", user=1)[1]
        self.assertEqual(shop1["wallet"]["balance"], 700)
        self.assertEqual(len(shop1["purchases"]), 1)
        self.assertEqual(shop1["purchases"][0]["status"], "simulated")
        self.assertEqual(shop1["purchases"][0]["points_cost"], 300)
        self.assertEqual(shop1["purchases"][0]["ldc_amount"], "0.50")

        # 4. User 1 tries to purchase again -> blocked by user_daily_limit=1
        code, err_res = self.request("/api/shop/purchase", {"product_id": pid}, user=1)
        self.assertEqual(code, 400)
        self.assertIn("单人兑换限额", err_res["error"])
        self.assertEqual(self.request("/api/shop", user=1)[1]["wallet"]["balance"], 700)

        # 5. User 2 purchases -> succeeds (reaches total_daily_limit=2)
        code, purchase_res2 = self.request("/api/shop/purchase", {"product_id": pid}, user=2)
        self.assertEqual(code, 200)
        self.assertEqual(self.request("/api/shop", user=2)[1]["wallet"]["balance"], 700) # 1000 - 300 = 700

        # 6. User 3 has points but total quota for this product is exhausted
        with app.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            credits.credit_checkin(conn, {"id": "3", "username": "user3"}, 1000, "seed-user3", self.now)
        code, err_res2 = self.request("/api/shop/purchase", {"product_id": pid}, user=3)
        self.assertEqual(code, 400)
        self.assertIn("全站兑换限额已满", err_res2["error"])
        self.assertEqual(self.request("/api/shop", user=3)[1]["wallet"]["balance"], 1000)

    def test_purchase_ldc_auto_delivery_live_and_failure_refund(self):
        # Product 0.50 LDC for 200 points
        code, res = self.request("/api/admin/products", {
            "category": "LDC", "name": "即时到账 LDC", "description": "实时接口分发",
            "points_price": 200, "ldc_amount": "0.50", "user_daily_limit": 0, "total_daily_limit": 0, "is_active": True
        }, admin=True)
        pid = res["product"]["id"]

        with app.db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            credits.credit_checkin(conn, {"id": "10", "username": "user10"}, 500, "seed-user10", self.now)
        # A) Successful live dispatch
        with patch.dict(os.environ, {"LDC_LIVE": "true", "LDC_CLIENT_ID": "client", "LDC_CLIENT_SECRET": "secret"}):
            with patch.object(app, "json_request", return_value={"code": 1, "data": {"trade_no": "REAL-LDC-123"}}) as mock_dist:
                code, p_res = self.request("/api/shop/purchase", {"product_id": pid}, user=10)
                self.assertEqual(code, 200)
                self.assertEqual(p_res["status"], "success")
                self.assertEqual(p_res["trade_no"], "REAL-LDC-123")
                self.assertEqual(self.request("/api/shop", user=10)[1]["wallet"]["balance"], 300)
                self.assertEqual(mock_dist.call_count, 1)
                call_data = mock_dist.call_args.kwargs["data"]
                self.assertEqual(call_data["user_id"], 10)
                self.assertEqual(call_data["username"], "user10")
                self.assertEqual(call_data["amount"], "0.50")

        # B) Failed live dispatch -> auto refund points!
        with patch.dict(os.environ, {"LDC_LIVE": "true", "LDC_CLIENT_ID": "client", "LDC_CLIENT_SECRET": "secret"}):
            with patch.object(app, "json_request", return_value={"code": -1, "error_msg": "商户可用余额不足"}):
                code, p_res = self.request("/api/shop/purchase", {"product_id": pid}, user=10)
                self.assertEqual(code, 200)
                self.assertEqual(p_res["status"], "failed")
                # Points were refunded back to 300!
                shop10 = self.request("/api/shop", user=10)[1]
                self.assertEqual(shop10["wallet"]["balance"], 300)
                # Ledger has purchase (-200) and refund (+200)
                deltas = [item["delta"] for item in shop10["ledger"]]
                self.assertIn(-200, deltas)
                self.assertIn(200, deltas)

        # C) Insufficient balance
        code, err = self.request("/api/shop/purchase", {"product_id": pid}, user=999) # user 999 has 0 points
        self.assertEqual(code, 400)
        self.assertIn("余额不足", err["error"])


    def test_distribute_without_code_preserves_trade_and_does_not_refund(self):
        calls = []

        class LDCHandler(app.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, payload))
                body = json.dumps({"error_msg": "", "data": {
                    "out_trade_no": payload["out_trade_no"], "trade_no": "119693406501863424",
                }}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        upstream = app.CheckinServer(("127.0.0.1", 0), LDCHandler)
        worker = threading.Thread(target=upstream.serve_forever, daemon=True)
        worker.start()
        try:
            self.seed_wallet(1)
            pid = self.quota_product("1.00")
            request = {"product_id": pid, "request_id": "same-purchase-request-1"}
            with patch.dict(os.environ, {"LDC_LIVE": "true", "LDC_CLIENT_ID": "client",
                                        "LDC_CLIENT_SECRET": "secret",
                                        "LDC_API_BASE": f"http://127.0.0.1:{upstream.server_port}"}):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: self.request("/api/shop/purchase", request, user=1), range(2)))
                replay = self.request("/api/shop/purchase", request, user=1)
            for code, result in [*results, replay]:
                self.assertEqual(code, 200, result)
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["order"]["trade_no"], "119693406501863424")
                self.assertEqual(result["order"]["order_no"], results[0][1]["order"]["order_no"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "/lpay/distribute")
            self.assertEqual(calls[0][1]["out_trade_no"], replay[1]["order"]["order_no"])
            shop = self.request("/api/shop", user=1)[1]
            self.assertEqual(shop["wallet"]["balance"], 900)
            self.assertEqual(shop["quota"]["used"], "1.00")
            self.assertEqual([item["delta"] for item in shop["ledger"] if item["kind"].startswith("shop_")], [-100])
            records = [json.loads(line) for line in Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8").splitlines()]
            outbound = next(row for row in records if row["event"] == "outbound.request")
            returned = next(row for row in records if row["event"] == "outbound.response")
            self.assertEqual(outbound["exchange_id"], returned["exchange_id"])
            self.assertEqual(outbound["headers"]["Authorization"], "[REDACTED]")
            self.assertEqual(json.loads(outbound["body"])["out_trade_no"], replay[1]["order"]["order_no"])
            self.assertEqual(json.loads(returned["body"])["data"]["trade_no"], "119693406501863424")
            self.assertEqual(returned["status"], 200)
            self.assertEqual(Path(os.environ["PAYMENT_LOG_PATH"]).stat().st_mode & 0o777, 0o600)
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join()

    def test_pending_reservation_survives_interruption_and_blocks_limits(self):
        self.seed_wallet(1)
        self.seed_wallet(2)
        pid = self.quota_product("1.00")
        other = self.quota_product("0.01")
        request_id = "interrupted-purchase-1"
        with app.db() as connection:
            connection.execute("UPDATE shop_products SET user_daily_limit=1, total_daily_limit=2 WHERE id=?", (pid,))

        def interrupted_dispatch(*_args):
            # Observe through a separate connection, as after a process restart.
            with app.db() as observer:
                row = observer.execute("SELECT status FROM shop_purchases WHERE request_id=?", (request_id,)).fetchone()
                self.assertEqual(row["status"], "pending")
                self.assertEqual(credits.wallet_view(observer, "1")["balance"], 900)
            raise RuntimeError("interrupted after submitting transfer")

        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with app.db() as connection:
                connection.execute("BEGIN IMMEDIATE")
                app.catalog.purchase_product(connection, {"id": "1", "username": "user1"}, pid,
                                             app.day_key(self.now), self.now, interrupted_dispatch,
                                             daily_ldc_limit=800, request_id=request_id)
        with patch.object(app, "dispatch_ldc", return_value=("success", "second-trade", "")) as dispatch:
            code, replay = self.request("/api/shop/purchase", {"product_id": pid, "request_id": request_id}, user=1)
            self.assertEqual((code, replay["status"]), (200, "pending"))
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": pid}, user=1)[0], 400)
            app.DAILY_LDC_LIMIT = 1
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": other}, user=2)[0], 400)
            dispatch.assert_not_called()
            app.DAILY_LDC_LIMIT = 800
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": pid}, user=2)[0], 200)
            self.assertEqual(self.request("/api/shop/purchase", {"product_id": pid}, user=3)[0], 400)
            self.assertEqual(dispatch.call_count, 1)
        shop = self.request("/api/shop", user=1)[1]
        product = next(item for item in shop["products"] if item["id"] == pid)
        self.assertEqual((product["user_today_count"], product["total_today_count"]), (1, 2))
        self.assertEqual(shop["wallet"]["balance"], 900)

    def test_distribute_ambiguous_response_keeps_points_and_quota(self):
        self.seed_wallet(1)
        pid = self.quota_product("1.00")
        responses = [({}, "uncertain"), ({"code": 1}, "uncertain"),
                     ({"message": "商户余额不足"}, "failed"), ({"msg": "拒绝分发"}, "failed")]
        with patch.dict(os.environ, {"LDC_LIVE": "true", "LDC_CLIENT_ID": "client", "LDC_CLIENT_SECRET": "secret"}):
            for response, expected in responses:
                with self.subTest(response=response), patch.object(app, "json_request", return_value=response):
                    code, result = self.request("/api/shop/purchase", {"product_id": pid}, user=1)
                    self.assertEqual((code, result["status"]), (200, expected))
        shop = self.request("/api/shop", user=1)[1]
        self.assertEqual(shop["wallet"]["balance"], 800)
        self.assertEqual(shop["quota"]["used"], "2.00")

    def test_payment_logs_keep_http_errors_and_invalid_json_without_truncation(self):
        large_body = ("网关错误" + "x" * 1_000_010 + "END-OF-RESPONSE").encode("utf-8")

        class GatewayHandler(app.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.send_response(503 if self.path == "/lpay/error" else 200)
                self.send_header("Content-Length", str(len(large_body)))
                self.end_headers()
                self.wfile.write(large_body)

        upstream = app.CheckinServer(("127.0.0.1", 0), GatewayHandler)
        worker = threading.Thread(target=upstream.serve_forever, daemon=True)
        worker.start()
        try:
            for path, exception in [("/lpay/error", app.urllib.error.HTTPError), ("/lpay/invalid", ValueError)]:
                with self.assertRaises(exception):
                    app.json_request(f"http://127.0.0.1:{upstream.server_port}{path}")
            records = [json.loads(line) for line in Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8").splitlines()]
            responses = [row for row in records if row["event"] == "outbound.response"]
            self.assertEqual([row["status"] for row in responses], [503, 200])
            for response in responses:
                self.assertEqual(response["body"].encode("utf-8"), large_body)
            self.assertEqual([row["error_type"] for row in records if row["event"] == "outbound.error"], ["JSONDecodeError"])
        finally:
            upstream.shutdown()
            upstream.server_close()
            worker.join()

    def test_payment_log_redacts_encoded_signatures_and_preserves_repeated_parameters(self):
        url = "/payments/ldc/notify?out_trade_no=LDC123&%73ign=private-signature&money=1.00&money=2.00"
        self.assertEqual(self.request(url), (400, "fail"))
        records = [json.loads(line) for line in Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8").splitlines()]
        request = next(row for row in records if row["event"] == "inbound.request")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request["url"]).query)
        self.assertEqual(query["money"], ["1.00", "2.00"])
        self.assertEqual(query["out_trade_no"], ["LDC123"])
        self.assertNotIn("private-signature", json.dumps(records))

    def test_admin_user_search_includes_users_without_wallets_and_beyond_dashboard_limit(self):
        self.assertEqual(self.request("/api/admin/users?q=user77")[0], 401)
        self.request("/api/visit", {}, user=77)
        self.request("/api/visit", {})
        with app.db() as connection:
            connection.executemany("INSERT INTO points_wallets(user_id,username) VALUES (?,?)",
                                   [(str(index), f"member{index}") for index in range(1000, 1600)])
        code, result = self.request("/api/admin/users?q=@USER77", admin=True)
        self.assertEqual((code, result["users"]), (200, [{"user_id": "77", "username": "user77", "balance": 0}]))
        self.assertEqual(self.request("/api/admin/users?q=1599", admin=True)[1]["users"][0]["user_id"], "1599")
        self.assertEqual(self.request("/api/admin/users?q=%25", admin=True)[1]["users"], [])
        self.assertEqual(self.request("/api/admin/users?q=", admin=True)[0], 400)
        self.assertEqual(self.request("/api/admin/users?q=anon", admin=True)[1]["users"], [])

    def test_admin_credit_requires_both_secrets_and_valid_configuration(self):
        self.seed_wallet(1)
        body = {"user_id": "1", "amount": 250, "secondary_secret": self.secondary_secret, "request_id": "admin-credit-request-1"}
        self.assertEqual(self.request("/api/admin/points/add", body)[0], 401)
        for configured in ("", "plain-secret", "pbkdf2_sha256$1$bad$bad"):
            with patch.dict(os.environ, {"ADMIN_POINTS_PASSWORD_HASH": configured}):
                self.assertEqual(self.request("/api/admin/points/add", body, admin=True)[0], 503)
        with patch.dict(os.environ, {"ADMIN_POINTS_PASSWORD_HASH": self.secondary_hash}):
            for secret in ("wrong-secret", "", None):
                self.assertEqual(self.request("/api/admin/points/add", dict(body, secondary_secret=secret), admin=True)[0], 403)
            self.assertEqual(self.request("/api/admin", admin=True)[0], 200)
        self.assertEqual(self.request("/api/shop", user=1)[1]["wallet"]["balance"], 1000)
        self.assertNotIn(self.secondary_secret, Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8"))

    def test_admin_credit_is_atomic_and_parallel_replays_credit_once(self):
        self.request("/api/visit", {}, user=77)
        body = {"user_id": "77", "amount": "250", "secondary_secret": self.secondary_secret, "request_id": "admin-credit-request-77"}
        with patch.dict(os.environ, {"ADMIN_POINTS_PASSWORD_HASH": self.secondary_hash}):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.request("/api/admin/points/add", body, admin=True), range(4)))
            self.assertTrue(all(code == 200 and result["wallet"]["balance"] == 250 for code, result in results))
            self.assertEqual(self.request("/api/admin/points/add", dict(body, amount=251), admin=True)[0], 400)
            self.assertEqual(self.request("/api/admin/points/add", dict(body, user_id="99999"), admin=True)[0], 404)
            for amount in (0, -1, True, 1.5, "1.2", 100000001):
                with self.subTest(amount=amount):
                    self.assertEqual(self.request("/api/admin/points/add", dict(body, amount=amount, request_id="invalid-amount-request"), admin=True)[0], 400)
        shop = self.request("/api/shop", user=77)[1]
        self.assertEqual(shop["wallet"]["balance"], 250)
        self.assertEqual([(row["kind"], row["delta"], row["balance_after"]) for row in shop["ledger"]], [("admin_credit", 250, 250)])
        log_text = Path(os.environ["PAYMENT_LOG_PATH"]).read_text(encoding="utf-8")
        self.assertNotIn(self.secondary_secret, log_text)
        self.assertNotIn(self.secondary_hash, log_text)
        self.assertIn("[REDACTED]", log_text)

    def test_admin_credit_ledger_failure_and_balance_overflow_leave_wallet_unchanged(self):
        self.request("/api/visit", {}, user=77)
        body = {"user_id": "77", "amount": 10, "secondary_secret": self.secondary_secret, "request_id": "admin-credit-rollback-77"}
        with app.db() as connection:
            connection.execute("CREATE TRIGGER reject_admin_credit BEFORE INSERT ON points_ledger WHEN NEW.kind='admin_credit' BEGIN SELECT RAISE(ABORT,'forced failure'); END")
        with patch.dict(os.environ, {"ADMIN_POINTS_PASSWORD_HASH": self.secondary_hash}):
            self.assertEqual(self.request("/api/admin/points/add", body, admin=True)[0], 500)
            with app.db() as connection:
                self.assertIsNone(connection.execute("SELECT * FROM points_wallets WHERE user_id='77'").fetchone())
                connection.execute("DROP TRIGGER reject_admin_credit")
            self.assertEqual(self.request("/api/admin/points/add", body, admin=True)[1]["wallet"]["balance"], 10)
            with app.db() as connection:
                connection.execute("UPDATE points_wallets SET balance=? WHERE user_id='77'", (credits.MAX_POINTS,))
            self.assertEqual(self.request("/api/admin/points/add", dict(body, request_id="admin-credit-overflow-77"), admin=True)[0], 400)
        self.assertEqual(self.request("/api/shop", user=77)[1]["wallet"]["balance"], credits.MAX_POINTS)

    def test_intermediate_ldc_history_preserved_without_minting_points(self):
        with app.db() as connection:
            connection.execute("DROP TABLE entries")
            connection.execute("CREATE TABLE entries(day TEXT,user_id TEXT,amount TEXT,payout_status TEXT)")
            connection.execute("INSERT INTO entries VALUES ('2026-10-25','1','1.00','success')")
            connection.execute("INSERT INTO checkin_settings(key,value) VALUES ('reward_tiers',?)", (json.dumps([{"through": 10, "amount": "1.25"}]),))
        app.init_db()
        with app.db() as connection:
            legacy = connection.execute("SELECT amount,payout_status FROM legacy_ldc_entries").fetchone()
            self.assertEqual(tuple(legacy), ("1.00", "success"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)
            self.assertEqual(app.settings(connection)["reward_tiers"], [{"through": 10, "amount": 1250}])
        app.init_db()
        self.assertEqual(self.request("/api/shop", user=1)[1]["wallet"]["balance"], 0)


if __name__ == "__main__":
    unittest.main()
