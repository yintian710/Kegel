from __future__ import annotations

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.config import Settings
from app.service import auth
from app.utils.exceptions import APIError
from app.utils.result import bad
from app.views._common import frontend_url, set_cookie

router = APIRouter(prefix="/api/auth")


@router.get("/linuxdo/start")
async def start(next: str = "/"):
    url, state_cookie = auth.start_oauth(next)
    response = RedirectResponse(url, status_code=302)
    set_cookie(response, auth.OAUTH_COOKIE, state_cookie, auth.OAUTH_COOKIE_SECONDS)
    return response


@router.get("/linuxdo/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    try:
        user, next_path = await auth.finish_oauth(code, state, request.cookies.get(auth.OAUTH_COOKIE))
    except (httpx.HTTPError, ValueError, KeyError):
        return bad("认证服务暂不可用，请重新登录", 502)
    response = RedirectResponse(frontend_url(next_path), status_code=303)
    set_cookie(response, auth.SESSION_COOKIE, auth.session_cookie_value(user), Settings.LOGIN_SESSION_SECONDS)
    set_cookie(response, auth.OAUTH_COOKIE, "", 0)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(frontend_url("/"), status_code=303)
    set_cookie(response, auth.SESSION_COOKIE, "", 0)
    return response
