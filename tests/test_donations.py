from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.config import Settings
from app.service import donations

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def merchant(monkeypatch):
    monkeypatch.setattr(Settings, "LDC_DONATION_ENABLED", True)
    monkeypatch.setattr(Settings, "LDC_CLIENT_ID", "merchant")
    monkeypatch.setattr(Settings, "LDC_CLIENT_SECRET", "test-secret")


def callback(order, trade_no="T-1", **changes):
    params = {"pid": "merchant", "trade_no": trade_no, "out_trade_no": order["order_no"], "type": "epay",
              "name": "LDC 赞助", "money": order["amount"], "trade_status": "TRADE_SUCCESS"}
    params.update(changes)
    params["sign"] = donations._sign(params, "test-secret")
    return "/api/payments/ldc/notify?" + urlencode(params)


async def test_donation_requires_enabled_merchant_and_login(client):
    assert (await client.request("/api/donations/create", {"amount": "3.00"}, user=1))[0] == 409
    assert (await client.request("/api/donations/create", {"amount": "3.00"}))[0] == 401
    assert (await client.request("/api/donations"))[1]["donation_ready"] is False


async def test_verified_notification_ranks_once_without_points(client, merchant):
    code, created = await client.request("/api/donations/create", {"amount": "3.00"}, user=1)
    assert code == 200, created
    order, payment = created["order"], created["payment"]
    assert payment["action"].endswith("/epay/pay/submit.php") and payment["fields"]["sign_type"] == "MD5"
    assert payment["fields"]["return_url"].endswith("/donate?donation=" + order["order_no"])
    assert payment["fields"]["notify_url"].endswith("/api/payments/ldc/notify")
    for amount in ("0", "0.001", "10000.01", "-1", 3, None):
        assert (await client.request("/api/donations/create", {"amount": amount}, user=1))[0] == 409
    # 浏览器回跳与伪造参数不会上榜。
    assert (await client.request("/api/donations"))[1]["donation_leaderboard"] == []
    assert await client.request(callback(order, sign_type="MD5") + "&sign_type=SHA1") == (400, "fail")
    assert await client.request(callback(order, money="2.00")) == (400, "fail")
    assert await client.request("/api/payments/ldc/notify?out_trade_no=x&money=1&money=2") == (400, "fail")
    assert await client.request(callback(order)) == (200, "success")
    assert await client.request(callback(order)) == (200, "success")  # 重复通知幂等
    assert await client.request(callback(order, trade_no="T-2")) == (400, "fail")
    board = (await client.request("/api/donations", user=1))[1]
    assert board["donation_leaderboard"] == [{"rank": 1, "username": "user1", "amount": "3.00", "count": 1}]
    assert board["donation_orders"][0]["status"] == "paid"
    assert (await client.request("/api/shop", user=1))[1]["wallet"]["balance"] == 0


async def test_payment_log_redacts_secrets_and_keeps_business_fields(client, merchant):
    _, created = await client.request("/api/donations/create", {"amount": "1.50"}, user=1)
    await client.request(callback(created["order"]))
    await client.request("/api/payments/ldc/notify?out_trade_no=LDC123&%73ign=private-signature&money=1.00&money=2.00")
    text = Path(Settings.PAYMENT_LOG_PATH).read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines()]
    assert "private-signature" not in text and "test-secret" not in text
    events = [record["event"] for record in records]
    assert "inbound.request" in events and "callback.accepted" in events and "callback.rejected" in events
    accepted = next(record for record in records if record["event"] == "callback.accepted")
    assert accepted["out_trade_no"] == [created["order"]["order_no"]]
    assert "[REDACTED]" in next(r for r in records if r["event"] == "inbound.request" and "LDC123" in r["url"])["url"]
