from __future__ import annotations

import asyncio

import pytest

from app.infrastructure.database import execute, fetch
from app.service import auth, checkin
from tests.conftest import SECONDARY_SECRET, START

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def open_day(client):
    code, _ = await client.request("/api/admin/open", {}, admin=True)
    assert code == 200


async def prepare(client, user):
    code, result = await client.request("/api/session/start", {}, user=user)
    assert code == 200, result
    session = result["session"]
    while session["step"] < 2:
        client.clock.advance(2)
        code, result = await client.request("/api/session/step", {"token": session["token"]}, user=user)
        assert code == 200, result
        session = result["session"]
    return session


async def complete(client, user):
    session = await prepare(client, user)
    client.clock.advance(2)
    code, result = await client.request("/api/session/complete", {"token": session["token"]}, user=user)
    assert code == 200, result
    return result["entry"]


async def test_admin_and_trigger_guards(client):
    assert (await client.request("/api/admin"))[0] == 401
    assert (await client.request("/api/admin/open", {}))[0] == 401
    assert (await client.request("/api/trigger/open", {}))[0] == 401
    assert (await client.request("/api/trigger/open", {}, headers={"X-Trigger-Token": "test-trigger"}))[0] == 200
    status = (await client.request("/api/status"))[1]
    assert status["is_open"] and status["open_reason"] == "trigger"
    # 未登录可以开始练习，但没有资格打卡。
    assert (await client.request("/api/session/start", {}))[1]["session"]["eligible"] is False
    assert (await client.request("/api/claim", {}))[0] == 401


async def test_envelope_and_string_ids(client):
    response = await client.request("/api/status", raw=True)
    assert response.json()["code"] == 0 and response.json()["msg"] == "success"
    assert response.headers["cache-control"] == "no-store"
    missing = await client.request("/api/nope", raw=True)
    assert missing.status_code == 404 and missing.json() == {"code": 404, "data": None, "msg": "页面或接口不存在"}
    created = await client.request("/api/admin/products", {
        "name": "0.50 LDC", "points_price": 10, "ldc_amount": "0.50", "is_active": True,
        "secondary_secret": SECONDARY_SECRET}, admin=True)
    assert created[0] == 200 and isinstance(created[1]["product"]["id"], str)
    assert int(created[1]["product"]["id"]) > 2 ** 40  # 雪花 ID


async def test_full_checkin_flow_awards_rank_and_claims_once(client):
    await open_day(client)
    entry = await complete(client, 1)
    assert entry["rank"] == 1 and entry["amount"] == 1000 and entry["reward_status"] == "unclaimed"
    code, claimed = await client.request("/api/claim", {}, user=1)
    assert code == 200 and claimed["wallet"]["balance"] == 1000
    code, again = await client.request("/api/claim", {}, user=1)
    assert code == 200 and again["wallet"]["balance"] == 1000
    ledger = (await client.request("/api/shop", user=1))[1]["ledger"]
    assert [row["kind"] for row in ledger] == ["checkin"] and isinstance(ledger[0]["id"], str)
    # 重复完成不会产生第二个名次。
    repeat = await complete(client, 1)
    assert repeat["rank"] == 1
    assert (await client.request("/api/status", user=2))[1]["total"] == 1


@pytest.mark.parametrize("prior,amount", [(9, 1000), (19, 500), (49, 100), (50, 0)])
async def test_reward_tier_boundaries(client, prior, amount):
    await open_day(client)
    for rank in range(1, prior + 1):
        await execute("INSERT INTO entries(day,user_id,username,rank,amount,completed_at,reward_status) "
                      "VALUES ('2026-10-26',$1,'x',$2,0,1,'none')", f"filler{rank}", rank)
    entry = await complete(client, 7)
    assert entry["rank"] == prior + 1 and entry["amount"] == amount
    assert entry["reward_status"] == ("unclaimed" if amount else "none")


async def test_concurrent_completions_get_distinct_ranks(client):
    await open_day(client)
    tokens = {user: (await prepare(client, user))["token"] for user in range(1, 7)}
    client.clock.advance(2)
    results = await asyncio.gather(*(
        client.request("/api/session/complete", {"token": token}, user=user) for user, token in tokens.items()))
    assert all(code == 200 for code, _ in results)
    assert sorted(result["entry"]["rank"] for _, result in results) == [1, 2, 3, 4, 5, 6]


async def test_concurrent_claims_credit_wallet_and_ledger_once(client):
    await open_day(client)
    await complete(client, 7)
    results = await asyncio.gather(*(client.request("/api/claim", {}, user=7) for _ in range(8)))
    assert all(code == 200 for code, _ in results)
    assert (await client.request("/api/shop", user=7))[1]["wallet"]["balance"] == 1000
    assert len(await fetch("SELECT 1 FROM points_ledger WHERE user_id='7'")) == 1


async def test_ledger_failure_rolls_back_wallet_and_claim(client):
    await open_day(client)
    await complete(client, 1)
    await execute("ALTER TABLE points_ledger ADD CONSTRAINT block_ledger CHECK (kind <> 'checkin')")
    try:
        code, _ = await client.request("/api/claim", {}, user=1)
        assert code == 409
    finally:
        await execute("ALTER TABLE points_ledger DROP CONSTRAINT block_ledger")
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 0
    assert (await client.request("/api/status", user=1))[1]["entry"]["reward_status"] == "unclaimed"


async def test_step_interval_and_token_replay(client):
    await open_day(client)
    await client.request("/api/admin/settings", {"min_step_seconds": 8}, admin=True)
    _, started = await client.request("/api/session/start", {}, user=1)
    token = started["session"]["token"]
    code, message = await client.request("/api/session/step", {"token": token}, user=1)
    assert code == 429 and "还需" in message
    client.clock.advance(8)
    code, stepped = await client.request("/api/session/step", {"token": token}, user=1)
    assert code == 200 and stepped["session"]["step"] == 1
    code, message = await client.request("/api/session/step", {"token": token}, user=1)
    assert code == 409 and "已使用" in message
    # 超过十分钟未继续则本轮失效。
    client.clock.advance(601)
    code, message = await client.request("/api/session/step", {"token": stepped["session"]["token"]}, user=1)
    assert code == 409 and "十分钟" in message


async def test_anonymous_practice_never_ranks(client):
    await open_day(client)
    cookie_headers = {}
    response = await client.request("/api/session/start", {}, raw=True)
    assert response.status_code == 200 and "checkin_visitor=" in response.headers["set-cookie"]
    visitor_cookie = response.headers["set-cookie"].split(";")[0]
    cookie_headers = {"Cookie": visitor_cookie}
    session = response.json()["data"]["session"]
    for _ in range(2):
        client.clock.advance(2)
        session = (await client.request("/api/session/step", {"token": session["token"]}, headers=cookie_headers))[1]["session"]
    client.clock.advance(2)
    code, done = await client.request("/api/session/complete", {"token": session["token"]}, headers=cookie_headers)
    assert code == 200 and done["entry"] is None and done["session"]["eligible"] is False
    assert (await client.request("/api/status"))[1]["total"] == 0


async def test_auto_round_validation_and_repeat_does_not_duplicate_reward(client):
    await open_day(client)
    for repetitions, interval in [(0, 2), (21, 2), (True, 2), (2, 1), (2, 6), (2, 2.5)]:
        code, _ = await client.request("/api/session/start", {"mode": "auto", "repetitions": repetitions,
                                                              "interval_seconds": interval}, user=1)
        assert code == 400, (repetitions, interval)
    for _ in range(2):
        _, started = await client.request("/api/session/start", {"mode": "auto", "repetitions": 3,
                                                                 "interval_seconds": 2}, user=1)
        session = started["session"]
        for _ in range(2):
            client.clock.advance(2)
            session = (await client.request("/api/session/step", {"token": session["token"]}, user=1))[1]["session"]
        client.clock.advance(2)
        code, done = await client.request("/api/session/complete", {"token": session["token"]}, user=1)
        assert code == 200 and done["entry"]["rank"] == 1
    assert (await client.request("/api/status", user=1))[1]["total"] == 1


async def test_deadline_rollover_resets_rank_but_keeps_wallet(client):
    day = await checkin.ensure_day(client.clock.value)
    assert day["opened_at"] is None
    await open_day(client)
    await complete(client, 1)
    await client.request("/api/claim", {}, user=1)
    client.clock.advance(15 * 3600 + 60)  # 当天 23:01 已过最晚开启时间
    assert (await client.request("/api/status"))[1]["is_open"] is True
    client.clock.value = START + 24 * 3600
    status = (await client.request("/api/status", user=1))[1]
    assert status["day"] == "2026-10-27" and status["is_open"] is False and status["total"] == 0
    assert status["wallet"]["balance"] == 1000


async def test_periodic_visits_require_review_then_approval(client):
    await open_day(client)
    for _ in range(6):
        client.clock.advance(60)
        await client.request("/api/visit", {}, user=5)
    status = (await client.request("/api/status", user=5))[1]
    assert status["review"] and "固定周期" in status["review"]["reason"]
    code, message = await client.request("/api/claim", {}, user=5)
    assert code == 403 and "等待管理员审核" in message
    assert (await client.request("/api/admin/review", {"user_id": "5", "approved": True}, admin=True))[0] == 200
    assert (await client.request("/api/status", user=5))[1]["review"] is None
    assert (await client.request("/api/admin/review", {"user_id": "404", "approved": True}, admin=True))[0] == 404


async def test_invalid_settings_are_rejected_without_partial_save(client):
    for amount in ["NaN", "Infinity", -1, 0.5, True, 100000001]:
        code, _ = await client.request("/api/admin/settings", {
            "deadline": "21:00", "reward_tiers": [{"through": 10, "amount": amount}],
            "secondary_secret": SECONDARY_SECRET}, admin=True)
        assert code == 400
    assert (await client.request("/api/admin", admin=True))[1]["settings"]["deadline"] == "22:00"


async def test_reward_tiers_need_secondary_secret(client):
    body = {"reward_tiers": [{"through": 10, "amount": 1000}]}
    code, _ = await client.request("/api/admin/settings", body, headers={"X-Admin-Token": "test-admin"})
    assert code == 403
    code, _ = await client.request("/api/admin/settings", {**body, "secondary_secret": "wrong"}, admin=True)
    assert code == 403
    code, _ = await client.request("/api/admin/settings", {**body, "secondary_secret": SECONDARY_SECRET}, admin=True)
    assert code == 200
    assert (await client.request("/api/admin", admin=True))[1]["settings"]["reward_tiers"] == body["reward_tiers"]


async def test_condition_tick_opens_only_for_boolean_true(client, monkeypatch):
    await client.request("/api/admin/settings", {"condition_url": "http://condition.example/open"}, admin=True)
    answers = iter([{"open": "true"}, {"open": True}])

    async def fake(url, **_kw):
        return next(answers)

    monkeypatch.setattr(checkin, "json_request", fake)
    await checkin.tick()
    assert (await client.request("/api/status"))[1]["is_open"] is False
    checkin._next_condition = 0.0
    await checkin.tick()
    status = (await client.request("/api/status"))[1]
    assert status["is_open"] and status["open_reason"] == "condition"


async def test_session_cookie_signature_and_renewal(client):
    token = auth.sign_payload({"purpose": "session", "id": "1", "username": "alice", "exp": client.clock.value + 60})
    response = await client.http.get("/api/status", headers={"Cookie": f"linuxdo_session={token}"})
    assert response.json()["data"]["user"]["username"] == "alice"
    assert "linuxdo_session=" in response.headers["set-cookie"] and "Max-Age=432000" in response.headers["set-cookie"]
    forged = await client.http.get("/api/status", headers={"Cookie": f"linuxdo_session={token}x"})
    assert forged.json()["data"]["user"] is None
