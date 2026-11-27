from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.infrastructure.database import execute, fetch, fetch_one
from app.service import catalog
from tests.conftest import ADMIN_USER_ID, SECONDARY_SECRET

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def make_product(client, amount="1.00", price=100, **extra):
    body = {"category": "LDC", "name": f"{amount} LDC", "description": "d", "points_price": price,
            "ldc_amount": amount, "is_active": True, "secondary_secret": SECONDARY_SECRET, **extra}
    code, result = await client.request("/api/admin/products", body, admin=True)
    assert code == 200, result
    return result["product"]["id"]


async def seed_wallet(user, balance=1000):
    await execute("INSERT INTO points_wallets(user_id,username,balance) VALUES ($1,$2,$3) "
                  "ON CONFLICT(user_id) DO UPDATE SET balance=$3", str(user), f"user{user}", balance)


def buy(client, user, product_id, request_id=None):
    return client.request("/api/shop/purchase", {"product_id": product_id,
                                                 "request_id": request_id or f"request-{user}-{product_id}-0001"}, user=user)


async def test_product_crud_requires_secondary_secret_and_lists_limits(client):
    code, _ = await client.request("/api/admin/products", {"name": "x", "points_price": 1, "is_active": True}, user=ADMIN_USER_ID)
    assert code == 403
    product_id = await make_product(client, "2.50", 500, user_daily_limit=1, total_daily_limit=5)
    code, listed = await client.request("/api/shop", user=1)
    product = listed["products"][0]
    assert product["id"] == product_id and product["user_remaining"] == 1 and product["total_remaining"] == 5
    code, saved = await client.request("/api/admin/products", {"id": product_id, "name": "改名", "points_price": 7, "ldc_amount": "2.50",
                                                                "is_active": True, "secondary_secret": SECONDARY_SECRET}, admin=True)
    assert code == 200 and saved["product"]["name"] == "改名"
    assert (await client.request(f"/api/admin/products/{product_id}/archive", {"secondary_secret": SECONDARY_SECRET}, admin=True))[0] == 200
    assert (await client.request("/api/shop", user=1))[1]["products"] == []
    assert len((await client.request("/api/admin", admin=True))[1]["products"]) == 1
    for bad in [{"ldc_amount": "0"}, {"ldc_amount": "10000.01"}, {"ldc_amount": "1.005"}, {"category": "X"}, {"user_daily_limit": -1}]:
        code, _ = await client.request("/api/admin/products", {"name": "n", "points_price": 1, "is_active": True,
                                                               "secondary_secret": SECONDARY_SECRET, **bad}, admin=True)
        assert code == 400, bad


async def test_simulated_purchase_debits_once_and_replays_request_id(client):
    product_id = await make_product(client, "1.00", 300)
    await seed_wallet(1)
    code, first = await buy(client, 1, product_id)
    assert code == 200 and first["status"] == "simulated" and first["trade_no"].startswith("SIM-")
    code, again = await buy(client, 1, product_id)
    assert code == 200 and again["order"]["order_no"] == first["order"]["order_no"]
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 700
    other = await make_product(client, "1.00", 1)
    code, message = await buy(client, 1, other, request_id=f"request-1-{product_id}-0001")
    assert code == 409 and "其他商品" in message
    assert (await client.request("/api/shop/purchase", {"product_id": product_id, "request_id": "short"}, user=1))[0] == 400
    assert (await client.request("/api/shop/purchase", {"product_id": product_id}))[0] == 401


async def test_insufficient_points_and_daily_limits(client):
    product_id = await make_product(client, "1.00", 100, user_daily_limit=1, total_daily_limit=2)
    await seed_wallet(1, 50)
    code, message = await buy(client, 1, product_id)
    assert code == 409 and "余额不足" in message
    for user in (1, 2, 3):
        await seed_wallet(user, 1000)
    assert (await buy(client, 1, product_id))[0] == 200
    code, message = await buy(client, 1, product_id, request_id="second-request-for-user1")
    assert code == 409 and "单人" in message
    assert (await buy(client, 2, product_id))[0] == 200
    code, message = await buy(client, 3, product_id)
    assert code == 409 and "全站兑换限额" in message
    assert (await client.request("/api/shop", user=3))[1]["wallet"]["balance"] == 1000


async def test_daily_ldc_quota_is_exact_across_products_and_failures_release_it(client, monkeypatch):
    monkeypatch.setattr(Settings, "DAILY_LDC_LIMIT", 1)
    small, rest = await make_product(client, "0.10", 10), await make_product(client, "0.90", 10)
    for user in (1, 2):
        await seed_wallet(user)
    assert (await buy(client, 1, small))[0] == 200
    assert (await buy(client, 1, rest))[0] == 200
    quota = (await client.request("/api/shop", user=1))[1]["quota"]
    assert quota == {"limit": "1.00", "used": "1.00", "remaining": "0.00"}
    code, message = await buy(client, 2, small)
    assert code == 409 and "额度不足" in message

    async def refused(*_args):
        return ("failed", "", "商户余额不足")

    monkeypatch.setattr(catalog, "dispatch_ldc", refused)
    await execute("UPDATE shop_purchases SET status='failed'")  # 释放额度
    code, result = await buy(client, 2, small)
    assert code == 200 and result["status"] == "failed"
    assert (await client.request("/api/shop", user=2))[1]["wallet"]["balance"] == 1000  # 自动退款
    kinds = [row["kind"] for row in await fetch("SELECT kind FROM points_ledger WHERE user_id='2' ORDER BY id")]
    assert kinds == ["shop_purchase", "shop_refund"]


async def test_concurrent_redemptions_respect_global_budget(client, monkeypatch):
    monkeypatch.setattr(Settings, "DAILY_LDC_LIMIT", 1000)
    first, second = await make_product(client, "500.00", 10), await make_product(client, "500.00", 10)
    for user in (1, 2, 3):
        await seed_wallet(user)
    results = await asyncio.gather(buy(client, 1, first), buy(client, 2, second), buy(client, 3, first))
    assert sorted(code for code, _ in results) == [200, 200, 409]


async def test_uncertain_delivery_keeps_debit_and_quota(client, monkeypatch):
    product_id = await make_product(client, "1.00", 100)
    await seed_wallet(1)

    async def unknown(*_args):
        return ("uncertain", "", "请求超时或网络异常: ReadTimeout")

    monkeypatch.setattr(catalog, "dispatch_ldc", unknown)
    code, result = await buy(client, 1, product_id)
    assert code == 200 and result["status"] == "uncertain"
    shop = (await client.request("/api/shop", user=1))[1]
    assert shop["wallet"]["balance"] == 900 and shop["quota"]["used"] == "1.00"
    assert shop["purchases"][0]["status"] == "uncertain"


async def test_reconcile_uncertain_order_by_hand(client, monkeypatch):
    product_id = await make_product(client, "1.00", 100, user_daily_limit=0)
    for user in (1, 2):
        await seed_wallet(user)

    async def unknown(*_args):
        return ("uncertain", "", "请求超时或网络异常: ReadTimeout")

    monkeypatch.setattr(catalog, "dispatch_ldc", unknown)
    refunded = (await buy(client, 1, product_id))[1]["order"]["order_no"]
    delivered = (await buy(client, 2, product_id))[1]["order"]["order_no"]

    def reconcile(order_no, body, **kw):
        return client.request(f"/api/admin/purchases/{order_no}/reconcile", body, **kw)

    # 须为管理员且通过二级密码；结果值必须明确。
    assert (await reconcile(refunded, {"result": "failed"}, user=1))[0] == 403
    assert (await reconcile(refunded, {"result": "failed"}, user=ADMIN_USER_ID))[0] == 403
    assert (await reconcile(refunded, {"result": "maybe"}, admin=True))[0] == 400
    assert (await reconcile("SO-NOPE", {"result": "failed"}, admin=True))[0] == 404

    code, result = await reconcile(refunded, {"result": "failed"}, admin=True)
    assert code == 200 and result["order"]["status"] == "failed"
    wallet = (await client.request("/api/shop", user=1))[1]
    assert wallet["wallet"]["balance"] == 1000 and wallet["quota"]["used"] == "1.00"  # 只剩另一笔占额度
    # 已处理的订单不能再次处理，也不会重复退款。
    assert (await reconcile(refunded, {"result": "failed"}, admin=True))[0] == 409
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 1000

    code, result = await reconcile(delivered, {"result": "success", "trade_no": " T-MANUAL "}, admin=True)
    assert code == 200 and result["order"]["status"] == "success" and result["order"]["trade_no"] == "T-MANUAL"
    assert (await client.request("/api/shop", user=2))[1]["wallet"]["balance"] == 900


async def test_pending_reservation_survives_delivery_crash(client, monkeypatch):
    product_id = await make_product(client, "1.00", 100, user_daily_limit=1)
    await seed_wallet(1)

    async def crash(*_args):
        raise RuntimeError("process died")

    monkeypatch.setattr(catalog, "dispatch_ldc", crash)
    code, _ = await buy(client, 1, product_id)
    assert code == 500
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 900
    assert [row["status"] for row in await fetch("SELECT status FROM shop_purchases")] == ["pending"]
    code, message = await buy(client, 1, product_id, request_id="another-request-after-crash")
    assert code == 409 and "单人" in message


async def test_live_dispatch_interprets_gateway_responses(client, monkeypatch):
    from app.common import linuxdo
    monkeypatch.setattr(Settings, "LDC_LIVE", True)
    monkeypatch.setattr(Settings, "LDC_CLIENT_ID", "merchant")
    monkeypatch.setattr(Settings, "LDC_CLIENT_SECRET", "merchant-secret")
    responses = iter([{"data": {"trade_no": "T1"}}, {"code": 1}, {}, {"error_msg": "余额不足"}, RuntimeError("timeout")])

    async def fake(url, **_kw):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(linuxdo, "json_request", fake)
    user = {"id": "1", "username": "alice"}
    outcomes = [await linuxdo.dispatch_ldc("SO-1", user, "1.00") for _ in range(5)]
    assert [item[0] for item in outcomes] == ["success", "uncertain", "uncertain", "failed", "uncertain"]
    assert outcomes[0][1] == "T1" and outcomes[3][2] == "余额不足"


async def test_admin_credit_requires_secret_and_is_idempotent(client):
    await client.request("/api/visit", {}, user=77)
    body = {"user_id": "77", "amount": "250", "secondary_secret": SECONDARY_SECRET, "request_id": "admin-credit-request-77"}
    assert (await client.request("/api/admin/points/add", body))[0] == 401
    assert (await client.request("/api/admin/points/add", {**body, "secondary_secret": "bad"}, admin=True))[0] == 403
    results = await asyncio.gather(*(client.request("/api/admin/points/add", body, admin=True) for _ in range(6)))
    assert all(code == 200 for code, _ in results)
    assert (await client.request("/api/shop", user=77))[1]["wallet"]["balance"] == 250
    code, message = await client.request("/api/admin/points/add", {**body, "amount": 251}, admin=True)
    assert code == 409 and "其他加积分" in message
    assert (await client.request("/api/admin/points/add", {**body, "request_id": "other-request-12345678", "user_id": "999"}, admin=True))[0] == 404
    for amount in (0, -5, 100_000_001, "1.5"):
        assert (await client.request("/api/admin/points/add", {**body, "request_id": "bad-amount-request-1", "amount": amount}, admin=True))[0] == 400


async def test_admin_user_search_finds_visitors_beyond_wallets(client):
    assert (await client.request("/api/admin/users?q=user77"))[0] == 401
    await client.request("/api/visit", {}, user=77)
    await client.request("/api/visit", {})
    code, found = await client.request("/api/admin/users?q=user77", admin=True)
    assert code == 200 and [(u["user_id"], u["username"], u["balance"]) for u in found["users"]] == [("77", "user77", 0)]
    assert (await client.request("/api/admin/users?q=77", admin=True))[1]["users"][0]["user_id"] == "77"
    assert (await client.request("/api/admin/users?q=", admin=True))[0] == 400
    assert (await client.request("/api/admin/users?q=a&q=b", admin=True))[0] == 400



async def test_no_payout_list_withholds_transfer_but_looks_normal_to_user(client, monkeypatch):
    calls = []

    async def fake_request(*args, **kwargs):
        calls.append(args)
        return {"data": {"trade_no": "REAL-1"}}

    monkeypatch.setattr("app.common.linuxdo.json_request", fake_request)
    monkeypatch.setattr(Settings, "LDC_LIVE", True)
    monkeypatch.setattr(Settings, "LDC_CLIENT_ID", "merchant")
    monkeypatch.setattr(Settings, "LDC_CLIENT_SECRET", "secret")
    product_id = await make_product(client, "1.00", 300)
    for user in (1, 2):
        await seed_wallet(user)

    settings_url = "/api/admin/settings"
    assert (await client.request(settings_url, {"no_payout_user_ids": ["1"]}, user=ADMIN_USER_ID))[0] == 403
    for bad in (["abc"], "1", [1], ["1"] * 201):
        code, _ = await client.request(settings_url, {"no_payout_user_ids": bad, "secondary_secret": SECONDARY_SECRET}, admin=True)
        assert code == 400, bad
    code, _ = await client.request(settings_url, {"no_payout_user_ids": ["1", "1"], "secondary_secret": SECONDARY_SECRET}, admin=True)
    assert code == 200

    code, blocked = await buy(client, 1, product_id)
    assert code == 200 and blocked["status"] == "success" and blocked["error"] == ""
    assert len(blocked["trade_no"]) == 18 and blocked["trade_no"].isdigit() and not calls
    assert "no_payout" not in blocked["order"]
    code, normal = await buy(client, 2, product_id)
    assert code == 200 and normal["trade_no"] == "REAL-1" and len(calls) == 1

    code, overview = await client.request("/api/admin", admin=True)
    assert overview["settings"]["no_payout_user_ids"] == ["1"]
    assert {p["user_id"]: p["no_payout"] for p in overview["purchases"]} == {"1": True, "2": False}

    for url in ("/api/shop", "/api/status"):
        body = (await client.request(url, user=1))[1]
        assert "no_payout" not in str(body) and "no_payout_user_ids" not in str(body)


async def test_ur_discount_applies_to_ldc_purchase(client, monkeypatch):
    from app.service import titles
    await titles.admin_save({"code": "UR-TEST", "rarity": "UR", "weight": 1, "name": "折扣UR", "discount_bp": 9500})
    ur_id = (await fetch("SELECT id FROM title_defs WHERE code='UR-TEST'"))[0]["id"]
    await execute("INSERT INTO user_titles(user_id,title_id,copies,first_obtained_at,last_obtained_at) "
                  "VALUES ('1',$1,1,0,0) ON CONFLICT(user_id,title_id) DO UPDATE SET copies=1", ur_id)
    await seed_wallet(1, 100000)
    product_id = await make_product(client, "100.00", 1000)
    code, result = await buy(client, 1, product_id, "req-discount-0001-0001")
    assert code == 200, result
    order = result["order"]
    assert order["points_cost"] == 950          # 95 折
    assert order["points_cost_original"] == 1000
    assert order["points_discount_saved"] == 50
    assert order["points_discount_bp"] == 9500
    code, shop = await client.request("/api/shop", user=1)
    assert shop["discount"]["bp"] == 9500 and shop["discount"]["saved_today"] == 50


async def test_discount_covers_tickets_and_skips_non_eligible(client, monkeypatch):
    from app.service import titles
    await titles.admin_save({"code": "UR-TEST2", "rarity": "UR", "weight": 1, "name": "折扣UR2", "discount_bp": 9500})
    ur_id = (await fetch("SELECT id FROM title_defs WHERE code='UR-TEST2'"))[0]["id"]
    await execute("INSERT INTO user_titles(user_id,title_id,copies,first_obtained_at,last_obtained_at) "
                  "VALUES ('1',$1,1,0,0) ON CONFLICT(user_id,title_id) DO UPDATE SET copies=1", ur_id)
    await seed_wallet(1, 10000)
    # 抽卡券（TICKET）也应享折扣：100 -> 95
    code, created = await client.request("/api/admin/products", {
        "category": "TICKET", "name": "单抽券", "description": "", "points_price": 100, "draw_count": 1,
        "is_active": True, "secondary_secret": SECONDARY_SECRET}, admin=True)
    assert code == 200, created
    ticket_id = created["product"]["id"]
    code, bought = await client.request("/api/titles/tickets/purchase",
                                         {"product_id": ticket_id, "request_id": "req-ticket-disc-0001"}, user=1)
    assert code == 200, bought
    assert bought["order"]["points_cost"] == 95
    assert bought["order"]["points_discount_saved"] == 5
    # 不可打折商品：不打折
    product_id = await make_product(client, "1.00", 100, discount_eligible=False)
    code, result = await buy(client, 1, product_id, "req-nodisc-0001-0001")
    assert code == 200, result
    assert result["order"]["points_cost"] == 100
    assert result["order"]["points_discount_saved"] == 0


def _http_error(status, payload):
    import httpx
    request = httpx.Request("GET", "https://credit.linux.do/epay/api.php")
    error = httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status, request=request))
    error.payload = payload
    return error


async def test_dispatch_http_error_keeps_credit_reason(monkeypatch):
    from app.common import linuxdo
    monkeypatch.setattr(Settings, "LDC_LIVE", True)
    monkeypatch.setattr(Settings, "LDC_CLIENT_ID", "merchant")
    monkeypatch.setattr(Settings, "LDC_CLIENT_SECRET", "merchant-secret")

    async def rejected(*_args, **_kw):
        raise _http_error(400, {"error_msg": "余额不足"})

    monkeypatch.setattr(linuxdo, "json_request", rejected)
    status, trade_no, error = await linuxdo.dispatch_ldc("SO-1", {"id": "1", "username": "alice"}, "1.00")
    assert status == "uncertain" and trade_no == "" and "HTTP 400" in error and "余额不足" in error


async def test_query_ldc_order_interprets_gateway_responses(monkeypatch):
    from app.common import linuxdo
    monkeypatch.setattr(Settings, "LDC_LIVE", True)
    monkeypatch.setattr(Settings, "LDC_CLIENT_ID", "merchant")
    monkeypatch.setattr(Settings, "LDC_CLIENT_SECRET", "merchant-secret")
    ok = {"code": 1, "status": 1, "trade_no": "T1", "out_trade_no": "SO-1", "money": "1.00"}
    responses = iter([
        ok,
        {**ok, "status": 0},
        {**ok, "money": "2.00"},
        {**ok, "out_trade_no": "SO-OTHER"},
        _http_error(404, {"code": -1, "msg": "订单不存在或已完成"}),
        _http_error(404, {"code": -1, "msg": "商户验证失败"}),
        _http_error(401, None),
        RuntimeError("timeout"),
    ])
    seen = []

    async def fake(url, **_kw):
        seen.append(url)
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(linuxdo, "json_request", fake)
    states = [(await linuxdo.query_ldc_order("SO-1", "1.00"))[0] for _ in range(8)]
    assert states == ["delivered", "unknown", "unknown", "unknown", "missing", "unknown", "unknown", "unknown"]
    assert "out_trade_no=SO-1" in seen[0] and "/epay/api.php" in seen[0]
    monkeypatch.setattr(Settings, "LDC_LIVE", False)
    assert (await linuxdo.query_ldc_order("SO-1", "1.00"))[0] == "unknown"  # 模拟模式不查询


async def _uncertain_orders(client, monkeypatch, users=(1, 2)):
    product_id = await make_product(client, "1.00", 100, user_daily_limit=0)

    async def unknown(*_args):
        return ("uncertain", "", "请求超时或网络异常: ReadTimeout")

    monkeypatch.setattr(catalog, "dispatch_ldc", unknown)
    orders = []
    for user in users:
        await seed_wallet(user)
        orders.append((await buy(client, user, product_id))[1]["order"]["order_no"])
    return orders


def _answer(monkeypatch, state, trade_no="", detail=""):
    async def fake(*_args):
        return (state, trade_no, detail)
    monkeypatch.setattr(catalog, "query_ldc_order", fake)


async def test_check_delivery_marks_success_when_credit_confirms(client, monkeypatch):
    (order_no,) = await _uncertain_orders(client, monkeypatch, users=(1,))
    _answer(monkeypatch, "delivered", "CREDIT-123")
    result = await catalog.check_delivery(order_no)
    assert result["outcome"] == "success" and result["order"]["status"] == "success"
    assert result["order"]["trade_no"] == "CREDIT-123" and result["order"]["error"] == ""
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 900  # 已发货，不退分
    assert (await catalog.check_delivery(order_no))["outcome"] == "settled"


async def test_check_delivery_fails_and_refunds_only_after_grace_period(client, clock, monkeypatch):
    (order_no,) = await _uncertain_orders(client, monkeypatch, users=(1,))
    _answer(monkeypatch, "missing", "", "订单不存在或已完成")

    clock.advance(catalog.MISSING_GRACE_SECONDS - 1)  # 不满 30 秒：仍可能在途，不判定
    waiting = await catalog.check_delivery(order_no)
    assert waiting["outcome"] == "waiting" and waiting["order"]["status"] == "uncertain"
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 900

    clock.advance(2)
    failed = await catalog.check_delivery(order_no)
    assert failed["outcome"] == "failed" and failed["order"]["status"] == "failed"
    assert "自动核对" in failed["order"]["error"]
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 1000
    # 再查不会重复退款
    assert (await catalog.check_delivery(order_no))["outcome"] == "settled"
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 1000
    kinds = [row["kind"] for row in await fetch("SELECT kind FROM points_ledger WHERE user_id='1' ORDER BY id")]
    assert kinds.count("shop_refund") == 1


async def test_check_delivery_leaves_unknown_results_alone(client, clock, monkeypatch):
    (order_no,) = await _uncertain_orders(client, monkeypatch, users=(1,))
    clock.advance(3600)
    _answer(monkeypatch, "unknown", "", "Credit 返回 HTTP 500：boom")
    result = await catalog.check_delivery(order_no)
    assert result["outcome"] == "unknown" and "HTTP 500" in result["message"]
    assert result["order"]["status"] == "uncertain"
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 900


async def test_user_can_check_own_order_with_cooldown(client, clock, monkeypatch):
    first, second = await _uncertain_orders(client, monkeypatch)
    catalog._last_user_check.clear()
    clock.advance(60)
    _answer(monkeypatch, "delivered", "T-USER")

    path = f"/api/shop/orders/{first}/check"
    assert (await client.request(path, {}))[0] == 401
    assert (await client.request(path, {}, user=2))[0] == 404  # 不能查别人的订单
    code, result = await client.request(path, {}, user=1)
    assert code == 200 and result["outcome"] == "success" and result["order"]["trade_no"] == "T-USER"
    assert result["wallet"]["balance"] == 900
    assert (await client.request(path, {}, user=1))[0] == 429  # 冷却期内重复查询被拒
    other = (await client.request(f"/api/shop/orders/{second}/check", {}, user=2))[1]
    assert other["outcome"] == "success"


async def test_background_and_admin_check_all_uncertain(client, clock, monkeypatch):
    first, second = await _uncertain_orders(client, monkeypatch)
    clock.advance(60)
    answers = {first: ("delivered", "T-1", ""), second: ("missing", "", "订单不存在或已完成")}

    async def fake(order_no, _amount):
        return answers[order_no]

    monkeypatch.setattr(catalog, "query_ldc_order", fake)
    assert (await client.request("/api/admin/purchases/check", {}, user=1))[0] == 403
    code, result = await client.request("/api/admin/purchases/check", {}, user=ADMIN_USER_ID)
    assert code == 200 and result["checked"] == {"success": 1, "failed": 1} and result["reasons"] == []
    statuses = {row["order_no"]: row["status"] for row in await fetch("SELECT order_no,status FROM shop_purchases")}
    assert statuses == {first: "success", second: "failed"}
    assert await catalog.check_all_uncertain() == {}  # 没有待核对订单时无事可做
    code, result = await client.request(f"/api/admin/purchases/{first}/check", {}, user=ADMIN_USER_ID)
    assert code == 200 and result["outcome"] == "settled"


async def test_check_all_reports_why_orders_stay_uncertain(client, clock, monkeypatch):
    await _uncertain_orders(client, monkeypatch)
    clock.advance(60)
    _answer(monkeypatch, "unknown", "", "未启用真实发货，无法向 Credit 查询")
    code, result = await client.request("/api/admin/purchases/check", {}, user=ADMIN_USER_ID)
    assert code == 200 and result["checked"] == {"unknown": 2}
    assert result["reasons"] == ["未启用真实发货，无法向 Credit 查询"]  # 相同原因只列一次


async def test_promo_discount_stacks_with_title_discount_and_expires(client, clock, monkeypatch):
    from app.utils import timeutil
    now = timeutil.now()
    product_id = await make_product(client, "1.00", 1000, promo_enabled=True, promo_discount_bp=8000, promo_ends_at=now + 3600)
    await seed_wallet(1, 5000)
    await seed_wallet(2, 5000)
    # 用户 2 持有 95 折称号
    await execute("INSERT INTO title_defs(id,code,rarity,weight,discount_bp,is_active,created_at) VALUES (9001,'t_ur','UR',1,9500,1,1)")
    await execute("INSERT INTO user_titles(user_id,title_id,copies,first_obtained_at,last_obtained_at) VALUES ('2',9001,1,1,1)")

    async def delivered(*_args):
        return ("success", "T-OK", "")

    monkeypatch.setattr(catalog, "dispatch_ldc", delivered)
    listed = (await client.request("/api/shop", user=1))[1]["products"][0]
    assert listed["promo_active"] is True and listed["price_now"] == 800  # 8 折
    assert (await client.request("/api/shop", user=2))[1]["products"][0]["price_now"] == 760  # 8 折再 95 折
    assert (await client.request("/api/shop"))[1]["products"][0]["price_now"] == 800  # 游客只看限时折扣

    assert (await buy(client, 1, product_id))[0] == 200
    assert (await buy(client, 2, product_id))[0] == 200
    rows = {row["user_id"]: row for row in await fetch("SELECT * FROM shop_purchases")}
    assert rows["1"]["points_cost"] == 800 and rows["1"]["points_promo_saved"] == 200 and rows["1"]["points_discount_saved"] == 0
    assert rows["2"]["points_cost"] == 760 and rows["2"]["points_promo_saved"] == 200 and rows["2"]["points_discount_saved"] == 40
    assert (await client.request("/api/shop", user=2))[1]["discount"]["saved_today"] == 40  # 限时折扣不占称号折扣的每日上限

    clock.advance(3601)  # 倒计时结束：恢复原价
    expired = (await client.request("/api/shop", user=1))[1]["products"][0]
    assert expired["promo_active"] is False and expired["price_now"] == 1000


async def test_promo_settings_are_validated(client):
    from app.utils import timeutil
    now = timeutil.now()
    base = {"category": "LDC", "name": "x", "points_price": 100, "ldc_amount": "1.00", "is_active": True,
            "secondary_secret": SECONDARY_SECRET}
    bad = [
        {"promo_enabled": True, "promo_discount_bp": 8000},                                  # 缺结束时间
        {"promo_enabled": True, "promo_discount_bp": 8000, "promo_ends_at": now - 1},        # 已过期
        {"promo_enabled": True, "promo_discount_bp": 10000, "promo_ends_at": now + 60},      # 没有折扣
        {"promo_enabled": True, "promo_discount_bp": 500, "promo_ends_at": now + 60},        # 低于 1 折
        {"promo_enabled": "yes", "promo_discount_bp": 8000, "promo_ends_at": now + 60},
    ]
    for extra in bad:
        code, _ = await client.request("/api/admin/products", {**base, **extra}, admin=True)
        assert code == 400, extra
    code, saved = await client.request("/api/admin/products", {**base, "promo_enabled": True, "promo_discount_bp": 8000,
                                                               "promo_ends_at": now + 60}, admin=True)
    assert code == 200 and saved["product"]["promo_bp"] == 8000
    code, saved = await client.request("/api/admin/products", {**base, "id": saved["product"]["id"], "promo_enabled": False}, admin=True)
    assert code == 200 and saved["product"]["promo_bp"] is None and saved["product"]["promo_ends_at"] is None  # 关闭即清空


async def test_ticket_product_can_have_promo(client, clock):
    from app.utils import timeutil
    code, result = await client.request("/api/admin/products", {
        "category": "TICKET", "name": "十连券", "points_price": 500, "draw_count": 10, "is_active": True,
        "promo_enabled": True, "promo_discount_bp": 9000, "promo_ends_at": timeutil.now() + 600,
        "secondary_secret": SECONDARY_SECRET}, admin=True)
    assert code == 200, result
    await seed_wallet(1, 2000)
    code, titles_view = await client.request("/api/titles", user=1)  # 称号页快捷兑换显示折后价，与实际扣款一致
    quick = titles_view["ticket_products"][0]
    assert code == 200 and quick["points_price"] == 500 and quick["price_now"] == 450 and quick["promo_active"] is True
    code, bought = await client.request("/api/titles/tickets/purchase", {"product_id": result["product"]["id"], "request_id": "ticket-promo-request-1"}, user=1)
    assert code == 200 and bought["order"]["points_cost"] == 450 and bought["order"]["points_promo_saved"] == 50
