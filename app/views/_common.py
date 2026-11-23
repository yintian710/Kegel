from __future__ import annotations

import orjson
from fastapi import Request, Response

from app.config import Settings
from app.service import auth
from app.utils.exceptions import APIError


def current_user(request: Request) -> dict | None:
    return request.state.user


def visitor_of(request: Request) -> str:
    """Anonymous visitor id; mints a signed cookie (attached by the middleware) on first use."""
    if request.state.visitor is None:
        request.state.visitor, request.state.new_visitor = auth.resolve_visitor(request.cookies.get(auth.VISITOR_COOKIE))
    return request.state.visitor


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def json_body(request: Request) -> dict:
    raw = await request.body()
    try:
        body = orjson.loads(raw or b"{}")
    except orjson.JSONDecodeError:
        raise APIError("请求数据格式错误") from None
    if not isinstance(body, dict):
        raise APIError("请求体需为 JSON 对象")
    return body


def set_cookie(response: Response, key: str, value: str, max_age: int) -> None:
    response.set_cookie(key, value, max_age=max_age, path=Settings.COOKIE_PATH, httponly=True, samesite="lax",
                        secure=Settings.APP_BASE_URL.startswith("https://"))


def frontend_url(path: str) -> str:
    """Absolute-path URL of a frontend route (`path` is one of auth.NEXT_PATHS)."""
    return Settings.FRONTEND_BASE_PATH.rstrip("/") + path
