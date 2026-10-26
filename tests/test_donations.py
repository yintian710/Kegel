import concurrent.futures
import hashlib
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import credits
import donations


class SponsorshipPayments(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "donations.db"
        self.environment = patch.dict(os.environ, {
            "LDC_DONATION_ENABLED": "true", "LDC_API_BASE": "https://credit.linux.do",
            "LDC_CLIENT_ID": "001", "LDC_CLIENT_SECRET": "test-merchant-secret",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.connection = self.connect()
        self.addCleanup(self.connection.close)
        donations.init_schema(self.connection)
        credits.init_schema(self.connection)
        self.now = 1792972800.0
        self.base = "https://sponsor.example"
        self.user = {"id": "1", "username": "alice"}
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            credits.credit_checkin(self.connection, self.user, 17, "initial-checkin", self.now)
        self.original_points = self.points()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def points(self):
        return {
            table: [tuple(row) for row in self.connection.execute(f"SELECT * FROM {table}")]
            for table in ("points_wallets", "points_ledger")
        }

    def create(self, amount="1.00", user=None, now=None):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            return donations.create_order(self.connection, user or self.user, amount, self.base,
                                          self.now if now is None else now)

    def signed(self, params):
        params = dict(params)
        text = "&".join(f"{key}={params[key]}" for key in sorted(params)
                        if key not in {"sign", "sign_type"} and params[key] != "")
        params["sign"] = hashlib.md5((text + "test-merchant-secret").encode()).hexdigest()
        return params

    def notification(self, created, trade_no="provider-trade-1"):
        fields = created["payment"]["fields"]
        return self.signed({
            "pid": fields["pid"], "trade_no": trade_no, "out_trade_no": fields["out_trade_no"],
            "type": "epay", "name": fields["name"], "money": fields["money"],
            "trade_status": "TRADE_SUCCESS", "sign_type": "MD5",
        })

    def settle(self, params, now=None):
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            donations.accept_notification(self.connection, params, self.now + 10 if now is None else now)

    def shop(self, user=None):
        return donations.shop_data(self.connection, user, self.base)

    def test_order_form_uses_official_signature_and_creates_no_payment_or_points(self):
        created = self.create("1.2")
        order, payment = created["order"], created["payment"]
        fields = payment["fields"]
        self.assertEqual(payment["action"], "https://credit.linux.do/epay/pay/submit.php")
        self.assertEqual(fields["pid"], "001")
        self.assertEqual(fields["type"], "epay")
        self.assertEqual(fields["money"], "1.20")
        self.assertEqual(fields["sign_type"], "MD5")
        self.assertEqual(fields["out_trade_no"], order["order_no"])
        self.assertEqual(fields["notify_url"], self.base + "/payments/ldc/notify")
        self.assertEqual(fields["return_url"], self.base + "/donate?donation=" + order["order_no"])
        canonical = ("money=1.20&name=LDC 赞助&notify_url=" + self.base + "/payments/ldc/notify"
                     + "&out_trade_no=" + order["order_no"] + "&pid=001&return_url=" + self.base
                     + "/donate?donation=" + order["order_no"] + "&type=epaytest-merchant-secret")
        self.assertEqual(fields["sign"], hashlib.md5(canonical.encode()).hexdigest())
        self.assertLessEqual(len(fields["notify_url"]), 100)
        self.assertLessEqual(len(fields["return_url"]), 100)
        self.assertNotIn("test-merchant-secret", repr(created))
        self.assertEqual(order["status"], "created")
        self.assertIsNone(order["paid_at"])
        self.assertTrue(order["created_at"].endswith("+00:00"))
        self.assertEqual(self.shop()["donation_leaderboard"], [])
        self.assertEqual(self.shop(self.user)["donation_orders"], [order])
        self.assertEqual(self.points(), self.original_points)

    def test_amount_boundaries_are_decimal_cents_without_rounding(self):
        for amount, expected in [("0.01", "0.01"), ("1", "1.00"), ("10000.00", "10000.00")]:
            with self.subTest(amount=amount):
                self.assertEqual(self.create(amount)["order"]["amount"], expected)
        for amount in [None, True, 1, 1.0, [], {}, "", "0", "0.00", "-1.00", "+1.00",
                       ".01", "1.", "01.00", "1.001", "10000.01", "10001", "999999999999",
                       "1e2", "NaN", "Infinity", " 1.00", "1.00\n", "１.００"]:
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.create(amount)
        self.assertEqual(len(self.shop(self.user)["donation_orders"]), 3)

    def test_disabled_or_invalid_merchant_configuration_fails_closed(self):
        cases = [
            {"LDC_DONATION_ENABLED": "false"}, {"LDC_DONATION_ENABLED": "yes"},
            {"LDC_CLIENT_ID": ""}, {"LDC_CLIENT_SECRET": ""},
            {"LDC_CLIENT_ID": "001&pid=002"}, {"LDC_CLIENT_SECRET": "secret\n"},
            {"LDC_API_BASE": "http://credit.linux.do"},
            {"LDC_API_BASE": "https://user:password@credit.linux.do"},
            {"LDC_API_BASE": "https://credit.linux.do?"},
            {"LDC_API_BASE": "https://credit.linux.do/#fragment"},
            {"LDC_API_BASE": "https://credit.linux.do:invalid"},
            {"LDC_API_BASE": "https://credit.linux.do:70000"},
            {"LDC_API_BASE": "http://localhost.evil.example"},
            {"LDC_API_BASE": "javascript:alert(1)"},
        ]
        for config in cases:
            with self.subTest(config=config), patch.dict(os.environ, config):
                self.assertFalse(self.shop()["donation_ready"])
                with self.assertRaises(ValueError):
                    self.create()
        for base in ["http://public.example", "https://" + "a" * 65 + ".example",
                     "https://valid.example/" + "a" * 55, "https://site.example?query=1"]:
            with self.subTest(base=base):
                self.assertFalse(donations.shop_data(self.connection, None, base)["donation_ready"])
                with self.connection, self.assertRaises(ValueError):
                    self.connection.execute("BEGIN IMMEDIATE")
                    donations.create_order(self.connection, self.user, "1.00", base, self.now)
        self.assertEqual(self.shop(self.user)["donation_orders"], [])
        with patch.dict(os.environ, {"LDC_API_BASE": "http://127.0.0.1:8001"}):
            self.assertTrue(donations.shop_data(self.connection, None, "http://localhost:8000")["donation_ready"])

    def test_creation_requires_authenticated_identity_and_an_explicit_transaction(self):
        with self.assertRaises(RuntimeError):
            donations.create_order(self.connection, self.user, "1.00", self.base, self.now)
        for user in [None, {}, {"id": "1"}, {"id": "", "username": "alice"},
                     {"id": 1, "username": "alice"}, {"id": "1", "username": "a\nb"}]:
            with self.subTest(user=user), self.connection, self.assertRaises(ValueError):
                self.connection.execute("BEGIN IMMEDIATE")
                donations.create_order(self.connection, user, "1.00", self.base, self.now)
        self.assertEqual(self.shop(self.user)["donation_orders"], [])

    def test_valid_callback_is_idempotent_and_does_not_change_station_points(self):
        created = self.create("2.50")
        callback = self.notification(created)
        self.settle(callback)
        paid = self.shop(self.user)["donation_orders"][0]
        self.settle(callback, self.now + 999)
        without_optional_sign_type = dict(callback)
        without_optional_sign_type.pop("sign_type")
        self.settle(without_optional_sign_type)
        self.assertEqual(self.shop(self.user)["donation_orders"], [paid])
        self.assertEqual(paid["status"], "paid")
        self.assertIsNotNone(paid["paid_at"])
        self.assertEqual(self.shop()["donation_leaderboard"], [
            {"rank": 1, "username": "alice", "amount": "2.50", "count": 1},
        ])
        self.assertEqual(self.points(), self.original_points)

    def test_forged_or_mismatched_notifications_never_settle(self):
        created = self.create()
        original = self.notification(created)
        invalid = [dict(original, sign="0" * 32), dict(original, money="2.00")]
        for changes in [
            {"pid": "002"}, {"money": "2.00"}, {"money": "1.001"}, {"money": "1e0"},
            {"money": "0.00"}, {"money": "10000.01"}, {"type": "ldcpay"},
            {"trade_status": "WAIT_BUYER_PAY"}, {"trade_status": "TRADE_FINISHED"},
            {"out_trade_no": "LDC" + "f" * 32}, {"out_trade_no": "../order"},
            {"name": "other order"}, {"trade_no": ""}, {"trade_no": "bad&trade"},
            {"trade_no": "x" * 129}, {"trade_no": "bad\ntrade"},
            {"sign_type": "SHA256"}, {"unexpected": "signed-but-not-supported"},
        ]:
            invalid.append(self.signed(dict(original, **changes)))
        for key in original:
            if key != "sign_type":
                missing = dict(original)
                missing.pop(key)
                invalid.append(missing)
        invalid.extend([dict(original, pid=["001", "002"]), dict(original, money=1), None, []])
        for params in invalid:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.settle(params)
        self.assertEqual(self.shop()["donation_leaderboard"], [])
        self.assertEqual(self.shop(self.user)["donation_orders"][0]["status"], "created")
        self.assertEqual(self.points(), self.original_points)

    def test_settlement_remains_available_after_donations_are_disabled(self):
        callback = self.notification(self.create())
        with patch.dict(os.environ, {"LDC_DONATION_ENABLED": "false", "LDC_API_BASE": "invalid"}):
            self.assertFalse(self.shop()["donation_ready"])
            self.settle(callback)
        self.assertEqual(self.shop(self.user)["donation_orders"][0]["status"], "paid")

    def test_trade_numbers_cannot_pay_multiple_orders_or_replace_a_settlement(self):
        first, second = self.create(), self.create()
        self.settle(self.notification(first, "unique-trade"))
        with self.assertRaises(ValueError):
            self.settle(self.notification(second, "unique-trade"))
        with self.assertRaises(ValueError):
            self.settle(self.notification(first, "different-trade"))
        self.assertEqual(self.shop()["donation_leaderboard"][0]["count"], 1)
        self.assertEqual({item["order_no"]: item["status"] for item in self.shop(self.user)["donation_orders"]}, {
            first["order"]["order_no"]: "paid", second["order"]["order_no"]: "created",
        })

    def test_parallel_duplicate_callbacks_produce_one_immutable_settlement(self):
        callback = self.notification(self.create())
        barrier = threading.Barrier(2)

        def notify():
            connection = self.connect()
            try:
                barrier.wait(timeout=5)
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    donations.accept_notification(connection, callback, self.now + 10)
            finally:
                connection.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(notify) for _ in range(2)]
            for result in results:
                result.result(timeout=15)
        self.assertEqual(self.shop()["donation_leaderboard"], [
            {"rank": 1, "username": "alice", "amount": "1.00", "count": 1},
        ])
        self.assertEqual(self.points(), self.original_points)

    def test_caller_transaction_controls_atomic_order_and_settlement_rollback(self):
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                donations.create_order(self.connection, self.user, "1.00", self.base, self.now)
                raise RuntimeError("rollback")
        self.assertEqual(self.shop(self.user)["donation_orders"], [])
        callback = self.notification(self.create())
        with self.assertRaises(RuntimeError):
            donations.accept_notification(self.connection, callback, self.now)
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                donations.accept_notification(self.connection, callback, self.now)
                raise RuntimeError("rollback")
        self.assertEqual(self.shop()["donation_leaderboard"], [])
        self.settle(callback)
        self.assertEqual(self.shop()["donation_leaderboard"][0]["count"], 1)

    def test_rankings_sum_verified_orders_by_identity_with_stable_ties_and_private_history(self):
        def paid(user, amount, trade, when):
            created = self.create(amount, user, when - 1)
            self.settle(self.notification(created, trade), when)

        paid(self.user, "1.00", "a1", self.now + 10)
        paid({"id": "1", "username": "alice-renamed"}, "2.00", "a2", self.now + 30)
        paid({"id": "2", "username": "alice-renamed"}, "3.00", "b1", self.now + 5)
        paid({"id": "3", "username": "carol"}, "4.00", "c1", self.now + 20)
        paid({"id": "5", "username": "eve"}, "1.00", "e1", self.now + 40)
        paid({"id": "4", "username": "dave"}, "1.00", "d1", self.now + 40)
        self.create("10000.00", {"id": "6", "username": "unpaid"})
        public = self.shop()
        self.assertEqual(public["donation_leaderboard"], [
            {"rank": 1, "username": "carol", "amount": "4.00", "count": 1},
            {"rank": 2, "username": "alice-renamed", "amount": "3.00", "count": 1},
            {"rank": 3, "username": "alice-renamed", "amount": "3.00", "count": 2},
            {"rank": 4, "username": "dave", "amount": "1.00", "count": 1},
            {"rank": 5, "username": "eve", "amount": "1.00", "count": 1},
        ])
        self.assertEqual(public["donation_orders"], [])
        own = self.shop(self.user)["donation_orders"]
        other = self.shop({"id": "2", "username": "alice-renamed"})["donation_orders"]
        self.assertEqual(len(own), 2)
        self.assertEqual(len(other), 1)
        self.assertFalse({item["order_no"] for item in own} & {item["order_no"] for item in other})
        self.assertEqual(set(own[0]), {"order_no", "amount", "status", "created_at", "paid_at"})
        self.assertEqual(self.points(), self.original_points)

    def test_public_rankings_and_private_history_have_independent_limits(self):
        for index in range(51):
            user = {"id": str(index + 100), "username": f"donor-{index}"}
            created = self.create("1.00", user, self.now + index)
            self.settle(self.notification(created, f"trade-{index}"), self.now + index)
        for index in range(22):
            self.create("0.01", now=self.now + index)
        public = self.shop()["donation_leaderboard"]
        self.assertEqual(len(public), 50)
        self.assertEqual(public[0]["username"], "donor-0")
        self.assertEqual(public[-1]["username"], "donor-49")
        own = self.shop(self.user)["donation_orders"]
        self.assertEqual(len(own), 20)
        self.assertGreater(own[0]["created_at"], own[-1]["created_at"])
        self.assertEqual(self.shop({"id": "unknown", "username": "alice"})["donation_orders"], [])


if __name__ == "__main__":
    unittest.main()
