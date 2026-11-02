from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Minimal .env loader; variables already present in the process environment win."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key.isidentifier():
            raise ValueError(f".env 第 {number} 行格式错误")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f".env 第 {number} 行引号未闭合")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str) -> bool:
    return _env(name, "false").lower() == "true"


def _integer(name: str, default: int, low: int, high: int, message: str) -> int:
    raw = _env(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(message) from None
    if not low <= value <= high:
        raise ValueError(message)
    return value


def _frontend_base(value: str) -> str:
    stripped = value.strip().strip("/")
    return f"/{stripped}/" if stripped else "/"


def _admin_user_ids(raw: str) -> frozenset[str]:
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    if not all(item.isdigit() for item in ids):
        raise ValueError("ADMIN_USER_IDS 须为逗号分隔的 LINUX DO 用户 ID（纯数字）")
    return frozenset(ids)


_load_env()

_PORT = _integer("PORT", 7188, 1, 65535, "PORT 须为 1–65535 的整数")
_APP_BASE_URL = _env("APP_BASE_URL", f"http://localhost:{_PORT}").rstrip("/")
_LOCAL = urlsplit(_APP_BASE_URL).hostname in {"localhost", "127.0.0.1", "::1"}
_APP_SECRET = _env("APP_SECRET")
if not _LOCAL and len(_APP_SECRET) < 32:
    raise ValueError("生产环境必须配置至少 32 字符的 APP_SECRET")
if _env("SNOWFLAKE_WORKER_ID") == "" and not _LOCAL:
    raise ValueError("生产环境必须显式设置 SNOWFLAKE_WORKER_ID（0–1023）")


class Settings:
    """Static, env-only configuration. Validated once at import; invalid values raise."""

    ROOT = ROOT
    SITE_TZ_NAME = "Asia/Shanghai"
    SITE_TZ = ZoneInfo("Asia/Shanghai")
    LOGIN_SESSION_SECONDS = 5 * 24 * 60 * 60
    VISITOR_COOKIE_SECONDS = 365 * 24 * 60 * 60

    HOST = _env("HOST", "127.0.0.1")
    PORT = _PORT
    APP_BASE_URL = _APP_BASE_URL
    IS_LOCAL = _LOCAL
    # 前端挂载的路径前缀，默认 /；登录回跳与赞助回跳 URL 据此生成。
    FRONTEND_BASE_PATH = _frontend_base(_env("FRONTEND_BASE_PATH", "/"))

    DATABASE_URL = _env("DATABASE_URL", "postgres://postgres:postgres@127.0.0.1:5432/kegel")
    DB_AUTO_CREATE = False
    SNOWFLAKE_WORKER_ID = _integer("SNOWFLAKE_WORKER_ID", 0, 0, 1023, "SNOWFLAKE_WORKER_ID 须为 0–1023 的整数")

    APP_SECRET = (_APP_SECRET or secrets.token_urlsafe(48)).encode()
    ADMIN_USER_IDS = _admin_user_ids(_env("ADMIN_USER_IDS"))
    TRIGGER_TOKEN = _env("CHECKIN_TRIGGER_TOKEN")
    CONDITION_TOKEN = _env("CHECKIN_CONDITION_TOKEN")
    ADMIN_SECONDARY_PASSWORD = _env("ADMIN_SECONDARY_PASSWORD")
    ADMIN_POINTS_PASSWORD_HASH = _env("ADMIN_POINTS_PASSWORD_HASH") or _env("ADMIN_SECONDARY_PASSWORD_HASH")

    DAILY_LDC_LIMIT = _integer("DAILY_LDC_LIMIT", 800, 0, 100_000_000, "DAILY_LDC_LIMIT 须为 0–100000000 的整数 LDC")

    LINUXDO_CLIENT_ID = _env("LINUXDO_CLIENT_ID")
    LINUXDO_CLIENT_SECRET = _env("LINUXDO_CLIENT_SECRET")
    LINUXDO_REDIRECT_URI = _env("LINUXDO_REDIRECT_URI") or _APP_BASE_URL + "/api/auth/linuxdo/callback"

    LDC_DONATION_ENABLED = _flag("LDC_DONATION_ENABLED")
    LDC_LIVE = _flag("LDC_LIVE") or _flag("LDC_AUTO_DISPATCH")
    LDC_API_BASE = _env("LDC_API_BASE", "https://credit.linux.do").rstrip("/")
    LDC_CLIENT_ID = _env("LDC_CLIENT_ID")
    # 赞助验签要求密钥不含首尾空白，故不 strip。
    LDC_CLIENT_SECRET = os.environ.get("LDC_CLIENT_SECRET", "")

    PAYMENT_LOG_PATH = _env("PAYMENT_LOG_PATH") or str(ROOT / "checkin.payments.jsonl")

    @classmethod
    def oauth_ready(cls) -> bool:
        return bool(cls.LINUXDO_CLIENT_ID and cls.LINUXDO_CLIENT_SECRET)

    @classmethod
    def secret_values(cls) -> list[str]:
        """Configured credentials that must never reach the payment log."""
        values = [cls.LDC_CLIENT_SECRET, cls.LINUXDO_CLIENT_SECRET, cls.APP_SECRET.decode(),
                  cls.TRIGGER_TOKEN, cls.CONDITION_TOKEN, cls.ADMIN_POINTS_PASSWORD_HASH]
        return [value for value in values if value]
