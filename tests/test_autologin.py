from __future__ import annotations

import pytest

from app.config import Settings

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_auto_login_disabled_by_default(client):
    code, data = await client.request("/api/status")
    assert code == 200 and data["user"] is None
    assert (await client.request("/api/admin"))[0] == 401


async def test_auto_login_injects_fixed_admin(client, monkeypatch):
    monkeypatch.setattr(Settings, "AUTO_LOGIN_ENABLED", True)
    monkeypatch.setattr(Settings, "AUTO_LOGIN_USER_ID", "424242")
    monkeypatch.setattr(Settings, "AUTO_LOGIN_USERNAME", "yintian")
    monkeypatch.setattr(Settings, "AUTO_LOGIN_NAME", "yintian")
    monkeypatch.setattr(Settings, "ADMIN_USER_IDS", frozenset({"424242"}))
    code, data = await client.request("/api/status")  # 不带任何 Cookie
    assert code == 200
    assert data["user"] == {"id": "424242", "username": "yintian", "name": "yintian"}
    # 固定用户若在 ADMIN_USER_IDS 内，可直接访问管理后台
    assert (await client.request("/api/admin"))[0] == 200
