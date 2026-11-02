from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

# 在导入应用之前覆盖本机 .env，保证测试环境确定。
_PAYMENT_LOG = Path(tempfile.mkdtemp()) / "payments.jsonl"
os.environ.update({
    "PORT": "7188", "APP_BASE_URL": "http://localhost:7188", "APP_SECRET": "test-secret-test-secret-test-secret-1234",
    "ADMIN_TOKEN": "test-admin", "CHECKIN_TRIGGER_TOKEN": "test-trigger", "CHECKIN_CONDITION_TOKEN": "",
    "ADMIN_POINTS_PASSWORD_HASH": "", "ADMIN_SECONDARY_PASSWORD": "", "ADMIN_SECONDARY_PASSWORD_HASH": "",
    "LINUXDO_CLIENT_ID": "", "LINUXDO_CLIENT_SECRET": "", "LINUXDO_REDIRECT_URI": "",
    "LDC_DONATION_ENABLED": "false", "LDC_LIVE": "", "LDC_AUTO_DISPATCH": "", "LDC_CLIENT_ID": "",
    "LDC_CLIENT_SECRET": "", "LDC_API_BASE": "https://credit.linux.do", "DAILY_LDC_LIMIT": "800",
    "PAYMENT_LOG_PATH": str(_PAYMENT_LOG), "SNOWFLAKE_WORKER_ID": "1", "FRONTEND_BASE_PATH": "/",
})

import httpx
import pgserver
import pytest
import pytest_asyncio
from tortoise import connections

from app.config import ROOT, Settings
from app.infrastructure.database import close_db, init_db
from app.server import app
from app.service import auth, checkin
from app.utils import timeutil

SECONDARY_SECRET = '二级校验"&测试'
_SALT = "0123456789abcdef0123456789abcdef"
SECONDARY_HASH = "pbkdf2_sha256$600000$" + _SALT + "$" + hashlib.pbkdf2_hmac(
    "sha256", SECONDARY_SECRET.encode("utf-8"), bytes.fromhex(_SALT), 600000).hex()
START = 1792972800.0  # Asia/Shanghai 2026-10-26 08:00
TABLES = ("checkin_settings, days, visits, reviews, sessions, entries, points_wallets, points_ledger, "
          "practice_triggers, training_records, shop_products, shop_purchases, donation_orders, donation_settlements")


@pytest.fixture(scope="session")
def postgres(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"))
    yield server.get_uri().replace("postgresql://", "postgres://", 1)
    server.cleanup()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database(postgres):
    Settings.DATABASE_URL = postgres
    await init_db()
    await connections.get("default").execute_script((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
    yield
    await close_db()


class Clock:
    def __init__(self):
        self.value = START

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> float:
        self.value += seconds
        return self.value


@pytest.fixture
def clock(monkeypatch):
    instance = Clock()
    monkeypatch.setattr(timeutil, "now", instance)
    return instance


@pytest.fixture(autouse=True)
def _settings(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "ADMIN_POINTS_PASSWORD_HASH", SECONDARY_HASH)
    monkeypatch.setattr(Settings, "PAYMENT_LOG_PATH", str(tmp_path / "payments.jsonl"))
    monkeypatch.setattr(checkin, "_next_condition", 0.0)


class Client:
    def __init__(self, http: httpx.AsyncClient, clock: Clock):
        self.http, self.clock = http, clock

    def _headers(self, user, admin, headers) -> dict:
        result = {}
        if user is not None:
            token = auth.sign_payload({"purpose": "session", "id": str(user), "username": f"user{user}",
                                       "exp": self.clock.value + 86400 * 7})
            result["Cookie"] = f"{auth.SESSION_COOKIE}={token}"
        if admin:
            result["X-Admin-Token"] = "test-admin"
            result["X-Secondary-Password"] = quote(SECONDARY_SECRET)
        result.update(headers or {})
        return result

    async def request(self, path: str, body=None, *, user=None, admin=False, headers=None, raw: bool = False):
        """-> (http status, envelope data) for JSON, (status, text) for plain text. raw=True returns the response."""
        response = await self.http.request("GET" if body is None else "POST", path,
                                           json=body, headers=self._headers(user, admin, headers))
        self.http.cookies.clear()  # 身份只由显式传入的 Cookie 决定，不让 httpx 罐子跨请求带登录态
        if raw:
            return response
        if response.headers.get("content-type", "").startswith("application/json"):
            envelope = response.json()
            assert envelope["code"] in (0, response.status_code)
            return response.status_code, envelope["data"] if envelope["code"] == 0 else envelope["msg"]
        return response.status_code, response.text


@pytest_asyncio.fixture(loop_scope="session")
async def client(database, clock):
    await connections.get("default").execute_script(f"TRUNCATE {TABLES} CASCADE")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:7188") as http:
        api = Client(http, clock)
        code, _ = await api.request("/api/admin/settings", {"deadline": "22:00", "min_step_seconds": 1}, admin=True)
        assert code == 200
        yield api
