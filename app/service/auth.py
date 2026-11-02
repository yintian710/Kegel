from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import unquote, urlencode

from app.common import linuxdo
from app.config import Settings
from app.infrastructure.database import execute
from app.utils import timeutil
from app.utils.exceptions import APIError

SESSION_COOKIE = "linuxdo_session"
VISITOR_COOKIE = "checkin_visitor"
OAUTH_COOKIE = "oauth_state"
OAUTH_COOKIE_SECONDS = 600
NEXT_PATHS = frozenset({"/", "/practice", "/shop", "/donate", "/admin"})


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def sign_payload(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_b64(hmac.new(Settings.APP_SECRET, body.encode(), hashlib.sha256).digest())}"


def verify_payload(token: str | None) -> dict | None:
    try:
        body, signature = (token or "").split(".", 1)
        expected = _b64(hmac.new(Settings.APP_SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if not isinstance(payload, dict) or payload.get("exp", 0) <= timeutil.now():
            return None
        return payload
    except (ValueError, TypeError, UnicodeError):
        return None


# ── 会话 ──────────────────────────────────────────────────────────────────────

def user_from_cookie(cookie: str | None) -> dict | None:
    payload = verify_payload(cookie)
    if (not payload or payload.get("purpose") != "session" or not str(payload.get("id", "")).isdigit()
            or not payload.get("username")):
        return None
    return {"id": str(payload["id"]), "username": payload["username"],
            "name": payload.get("name") or payload["username"]}


def session_cookie_value(user: dict) -> str:
    return sign_payload({"purpose": "session", **user, "exp": timeutil.now() + Settings.LOGIN_SESSION_SECONDS})


def require_user(user: dict | None) -> dict:
    if not user:
        raise APIError("请先使用 LINUX DO 登录", 401)
    return user


def require_login_if_configured(user: dict | None) -> None:
    """Account pages demand a login only once OAuth is configured (otherwise there is nobody to log in as)."""
    if Settings.oauth_ready() and not user:
        raise APIError("请先使用 LINUX DO 登录", 401)


def require_admin(user: dict | None) -> None:
    if not user:
        raise APIError("请先使用 LINUX DO 登录", 401)
    if user["id"] not in Settings.ADMIN_USER_IDS:
        raise APIError("当前账号不是管理员", 403)


def require_trigger(token: str | None) -> None:
    if not Settings.TRIGGER_TOKEN or not hmac.compare_digest(token or "", Settings.TRIGGER_TOKEN):
        raise APIError("触发密钥未配置或不正确", 401)


def verify_secondary_secret(value) -> None:
    configured_hash = Settings.ADMIN_POINTS_PASSWORD_HASH
    plain = Settings.ADMIN_SECONDARY_PASSWORD
    if not configured_hash and not plain:
        raise APIError("未配置管理员二级密码（请在 .env 配置 ADMIN_SECONDARY_PASSWORD 或 ADMIN_POINTS_PASSWORD_HASH）", 503)
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise APIError("请输入有效的二级密码", 403)
    if plain:
        if not hmac.compare_digest(value, plain):
            raise APIError("二级密码不正确", 403)
        return
    parts = configured_hash.split("$")
    if (len(parts) != 4 or parts[0] != "pbkdf2_sha256" or parts[1] != "600000"
            or not re.fullmatch(r"[0-9a-f]{32}", parts[2]) or not re.fullmatch(r"[0-9a-f]{64}", parts[3])):
        raise APIError("未配置有效的二级密码哈希", 503)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), bytes.fromhex(parts[2]), 600000).hex()
    if not hmac.compare_digest(digest, parts[3]):
        raise APIError("二级密码不正确", 403)


def secondary_secret_from(body: dict, headers) -> str:
    return (body.get("secondary_secret") or body.get("secondary_password")
            or unquote(headers.get("X-Secondary-Password", "")) or unquote(headers.get("X-Secondary-Secret", "")))


# ── 访客 ──────────────────────────────────────────────────────────────────────

def resolve_visitor(cookie: str | None) -> tuple[str, str | None]:
    """Return (visitor id, new signed cookie value if one had to be minted)."""
    payload = verify_payload(cookie)
    visitor = payload.get("visitor") if payload and payload.get("purpose") == "visitor" else None
    if visitor:
        return visitor, None
    visitor = secrets.token_urlsafe(18)
    return visitor, sign_payload({"purpose": "visitor", "visitor": visitor,
                                  "exp": timeutil.now() + Settings.VISITOR_COOKIE_SECONDS})


def practice_identity(user: dict | None, visitor: str) -> dict:
    return user or {"id": f"anon:{visitor}", "username": "匿名访客"}


# ── OAuth ─────────────────────────────────────────────────────────────────────

def start_oauth(next_path: str) -> tuple[str, str]:
    """Return (authorize url, signed state cookie value)."""
    if not Settings.oauth_ready():
        raise APIError("尚未配置 LINUX DO Connect", 503)
    if next_path not in NEXT_PATHS:
        next_path = "/"
    state = secrets.token_urlsafe(32)
    cookie = sign_payload({"purpose": "oauth", "state": state, "next": next_path,
                           "exp": timeutil.now() + OAUTH_COOKIE_SECONDS})
    query = urlencode({"client_id": Settings.LINUXDO_CLIENT_ID, "redirect_uri": Settings.LINUXDO_REDIRECT_URI,
                       "response_type": "code", "scope": "user", "state": state})
    return f"{linuxdo.CONNECT_AUTHORIZE_URL}?{query}", cookie


async def finish_oauth(code: str, state: str, state_cookie: str | None) -> tuple[dict, str]:
    """Validate the callback, upsert the wallet and return (session user, frontend next path)."""
    saved = verify_payload(state_cookie)
    if not code or not saved or saved.get("purpose") != "oauth" or not hmac.compare_digest(state, saved.get("state", "")):
        raise APIError("OAuth 回调校验失败，请重新登录")
    profile = await linuxdo.exchange_code(code)
    if not profile:
        raise APIError("没有获取到登录令牌", 502)
    if not str(profile.get("id", "")).isdigit() or not isinstance(profile.get("username"), str) or not profile["username"]:
        raise APIError("登录服务返回的用户身份不完整", 502)
    await execute("INSERT INTO points_wallets(user_id,username) VALUES ($1,$2) "
                  "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
                  str(profile["id"]), profile["username"])
    user = {"id": str(profile["id"]), "username": profile["username"], "name": profile.get("name") or profile["username"]}
    next_path = saved.get("next")
    return user, next_path if next_path in NEXT_PATHS else "/"
