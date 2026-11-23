from __future__ import annotations

import pytest

from app.infrastructure.database import execute, fetch_one
from app.service import catalog, credits, titles
from app.utils import timeutil
from tests.conftest import ADMIN_USER_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def seed_pool():
    base = [("N-01", "N"), ("N-02", "N"), ("R-01", "R"), ("SR-01", "SR"),
            ("SSR-01", "SSR"), ("SSR-02", "SSR"), ("SSR-03", "SSR"), ("UR-01", "UR")]
    for code, rarity in base:
        await titles.admin_save({"code": code, "rarity": rarity, "weight": 1, "name": code})


async def make_product(draw_count: int, price: int, name: str) -> str:
    product = await catalog.save({"category": "TICKET", "name": name, "description": "",
                                  "points_price": price, "draw_count": draw_count, "is_active": True})
    return str(product["id"])


async def give_points(uid: int, amount: int, ref: str):
    await credits.grant_points({"id": str(uid), "username": f"user{uid}"}, amount, ref, timeutil.now())


async def give_tickets(uid: int, ticket_type: str, count: int, ref: str):
    await titles._ensure_state(str(uid))
    await titles._ticket_apply(str(uid), ticket_type, count, "admin", ref, timeutil.now())


async def give_title_copies(uid: int, code: str, count: int):
    row = await fetch_one("SELECT id FROM title_defs WHERE code=$1", code)
    for _ in range(count):
        await titles._give_title(str(uid), row["id"], timeutil.now())


async def test_purchase_ticket_with_points_and_idempotent(client):
    await seed_pool()
    product_id = await make_product(10, 475, "十连券")
    uid = 5001
    await give_points(uid, 1000, "seed-points-5001")
    body = {"product_id": product_id, "request_id": "req-purchase-5001-01"}
    code, data = await client.request("/api/titles/tickets/purchase", body, user=uid)
    assert code == 200, data
    assert data["status"] == "success"
    assert data["ticket_type"] == "ten"
    assert data["tickets"]["ten"] == 1
    assert data["wallet"]["balance"] == 525
    # 同一 request_id 重放：不重复扣分、不重复发券
    code, data = await client.request("/api/titles/tickets/purchase", body, user=uid)
    assert code == 200
    assert data["tickets"]["ten"] == 1
    assert (await client.request("/api/titles", user=uid))[1]["wallet"]["balance"] == 525


async def test_draw_consumes_ticket_and_rejects_when_short(client):
    await seed_pool()
    uid = 5002
    await give_tickets(uid, "ten", 1, "seed-ten-5002")
    code, data = await client.request("/api/titles/draw", {"ticket_type": "ten", "request_id": "req-draw-5002-0001"},
                                      user=uid)
    assert code == 200, data
    assert len(data["results"]) == 10
    assert data["tickets"]["ten"] == 0
    # 券不足
    code, message = await client.request("/api/titles/draw", {"ticket_type": "ten", "request_id": "req-draw-5002-0002"},
                                         user=uid)
    assert code == 400 and "券不足" in message
    # 单抽券也没有
    code, message = await client.request("/api/titles/draw", {"ticket_type": "single", "request_id": "req-draw-5002-0003"},
                                         user=uid)
    assert code == 400


async def test_draw_idempotent_by_request_id(client):
    await seed_pool()
    uid = 5003
    await give_tickets(uid, "single", 2, "seed-single-5003")
    body = {"ticket_type": "single", "request_id": "req-draw-5003-0001"}
    code, first = await client.request("/api/titles/draw", body, user=uid)
    assert code == 200
    code, again = await client.request("/api/titles/draw", body, user=uid)
    assert code == 200
    assert first["batch"]["id"] == again["batch"]["id"]
    assert again["tickets"]["single"] == 1  # 只扣了一张


async def test_ten_pull_sr_floor_is_deterministic(client, monkeypatch):
    await seed_pool()
    uid = 5004
    await give_tickets(uid, "ten", 1, "seed-ten-5004")
    # 让 SSR 判定不触发（>=30），其余权重选择恒取第一项（N），从而依赖 10 连保底补 SR。
    monkeypatch.setattr(titles.secrets, "randbelow", lambda n: 999 if n == 1000 else 0)
    code, data = await client.request("/api/titles/draw", {"ticket_type": "ten", "request_id": "req-floor-5004-0001"},
                                      user=uid)
    assert code == 200, data
    rarities = [item["rarity"] for item in data["results"]]
    assert rarities == ["N"] * 9 + ["SR"]


async def test_hard_pity_forces_ssr(client):
    await seed_pool()
    uid = 5005
    await give_tickets(uid, "single", 1, "seed-single-5005")
    await titles._ensure_state(str(uid))
    await execute("UPDATE user_title_state SET pity=79 WHERE user_id=$1", str(uid))
    code, data = await client.request("/api/titles/draw", {"ticket_type": "single", "request_id": "req-pity-5005-0001"},
                                      user=uid)
    assert code == 200, data
    assert data["results"][0]["rarity"] == "SSR"
    assert data["pity"] == 0


async def test_smelt_random_upgrades_and_consumes(client):
    await seed_pool()
    uid = 5006
    await give_title_copies(uid, "N-01", 3)
    n_id = (await fetch_one("SELECT id FROM title_defs WHERE code='N-01'"))["id"]
    code, data = await client.request("/api/titles/smelt", {
        "mode": "random", "input_rarity": "N", "materials": [{"title_id": str(n_id), "count": 3}],
        "request_id": "req-smelt-5006-01"}, user=uid)
    assert code == 200, data
    assert data["output"]["rarity"] == "R"
    row = await fetch_one("SELECT copies FROM user_titles WHERE user_id=$1 AND title_id=$2", str(uid), n_id)
    assert row is None  # 熔炼到 0 删除


async def test_ur_craft_consumes_and_blocks_duplicate(client):
    await seed_pool()
    await titles.set_config("ur_recipes", [
        {"id": "r1", "output_code": "UR-01", "materials": ["SSR-01", "SSR-02", "SSR-03"]}])
    uid = 5007
    for code in ("SSR-01", "SSR-02", "SSR-03"):
        await give_title_copies(uid, code, 1)
    ids = {code: (await fetch_one("SELECT id FROM title_defs WHERE code=$1", code))["id"]
           for code in ("SSR-01", "SSR-02", "SSR-03")}
    materials = [{"title_id": str(ids[c]), "count": 1} for c in ("SSR-01", "SSR-02", "SSR-03")]
    code, data = await client.request("/api/titles/craft", {
        "recipe_id": "r1", "materials": materials, "request_id": "req-ur-5007-0001"}, user=uid)
    assert code == 200, data
    assert data["output"]["rarity"] == "UR"
    ur_id = (await fetch_one("SELECT id FROM title_defs WHERE code='UR-01'"))["id"]
    assert await fetch_one("SELECT 1 FROM user_titles WHERE user_id=$1 AND title_id=$2", str(uid), ur_id)
    # 再合成同一个 UR：409 且不扣材料（材料已不足也会先命中已拥有判断）
    code, message = await client.request("/api/titles/craft", {
        "recipe_id": "r1", "materials": materials, "request_id": "req-ur-5007-0002"}, user=uid)
    assert code == 409


async def test_checkin_grants_configured_tickets_and_is_idempotent(client):
    await seed_pool()
    uid = 6001
    code, _ = await client.request("/api/admin/settings", {
        "ticket_reward_tiers": [{"through": 10, "ticket_type": "ten", "count": 1}]}, admin=True)
    assert code == 200
    assert (await client.request("/api/admin/open", {}, admin=True))[0] == 200
    # 完成打卡
    code, started = await client.request("/api/session/start", {}, user=uid)
    assert code == 200, started
    session = started["session"]
    while session["step"] < 2:
        client.clock.advance(2)
        code, stepped = await client.request("/api/session/step", {"token": session["token"]}, user=uid)
        assert code == 200, stepped
        session = stepped["session"]
    client.clock.advance(2)
    code, done = await client.request("/api/session/complete", {"token": session["token"]}, user=uid)
    assert code == 200, done
    tickets = (await client.request("/api/titles", user=uid))[1]["tickets"]
    assert tickets["ten"] == 1
    # 重复发券（同一天）幂等
    today = timeutil.day_key(client.clock.value)
    await titles.grant_checkin_tickets(str(uid), 1, today, client.clock.value)
    tickets = (await client.request("/api/titles", user=uid))[1]["tickets"]
    assert tickets["ten"] == 1


async def test_equip_requires_ownership(client):
    await seed_pool()
    uid = 5008
    code, message = await client.request("/api/titles/equip", {"title_id": "1"}, user=uid)
    assert code == 409
    await give_title_copies(uid, "N-01", 1)
    n_id = (await fetch_one("SELECT id FROM title_defs WHERE code='N-01'"))["id"]
    code, data = await client.request("/api/titles/equip", {"title_id": str(n_id)}, user=uid)
    assert code == 200 and data["equipped_title_id"] == str(n_id)
