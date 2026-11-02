from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.infrastructure.database import execute, fetch
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
