from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from tortoise.exceptions import IntegrityError

from app.common import scheduler
from app.common.payment_log import payment_log, redact
from app.config import Settings
from app.infrastructure.database import close_db, init_db
from app.service import auth, checkin
from app.utils.exceptions import APIError
from app.utils.result import ORJSONResponse, bad
from app.views import routers

logger = logging.getLogger("kegel")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

MAX_BODY_BYTES = 65536
# 支付相关接口的完整请求/响应都写入支付对账日志。
AUDITED_PATHS = frozenset({"/api/shop", "/api/shop/purchase", "/api/donations", "/api/donations/create",
                           "/api/payments/ldc/notify", "/api/admin/points/add"})
SESSION_PREFIX = f"{auth.SESSION_COOKIE}=".encode()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    scheduler.setup(checkin.tick)
    logger.info("提肛打卡已启动: %s", Settings.APP_BASE_URL)
    logger.info("打卡奖励为站内积分；LDC 赞助不增加积分。")
    try:
        yield
    finally:
        scheduler.teardown()
        await close_db()


app = FastAPI(title="Kegel", lifespan=lifespan, default_response_class=ORJSONResponse,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
for router in routers:
    app.include_router(router)


# ── 异常 → 统一信封 ───────────────────────────────────────────────────────────

@app.exception_handler(APIError)
async def _api_error(_request: Request, exc: APIError):
    return bad(exc.message, exc.code)


@app.exception_handler(ValueError)
async def _value_error(_request: Request, exc: ValueError):
    return bad(str(exc), 409)


@app.exception_handler(IntegrityError)
async def _integrity_error(_request: Request, _exc: IntegrityError):
    return bad("数据冲突，请刷新后重试", 409)


@app.exception_handler(TypeError)
async def _type_error(request: Request, exc: TypeError):
    logger.warning("请求数据类型错误 %s: %s", request.url.path, exc)
    return bad("请求数据格式错误", 400)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, _exc: RequestValidationError):
    return bad("请求数据格式错误", 400)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_request: Request, exc: StarletteHTTPException):
    return bad("页面或接口不存在" if exc.status_code == 404 else str(exc.detail), exc.status_code)


# ── 全局中间件：身份、来源校验、支付审计、响应头 ───────────────────────────────

def _raw_url(request: Request) -> str:
    path = request.scope.get("raw_path", b"").decode("latin-1") or request.url.path
    return f"{path}?{request.url.query}" if request.url.query else path


def _header_lists(items) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for key, value in items:
        result.setdefault(key, []).append(value)
    return result


def _guard(request: Request) -> None:
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and origin != Settings.APP_BASE_URL:
            raise APIError("请求来源不匹配", 403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > MAX_BODY_BYTES:
            raise APIError("请求体过大", 413)


async def _capture(request: Request, response: Response) -> Response:
    if hasattr(response, "body_iterator"):
        body = b"".join([chunk async for chunk in response.body_iterator])
    else:  # 中间件自己生成的响应（如 500 兜底）没有流
        body = bytes(response.body)
    payment_log("inbound.response", exchange_id=request.state.payment_log_id, status=response.status_code,
                headers=_header_lists((key.decode("latin-1"), value.decode("latin-1"))
                                      for key, value in response.raw_headers),
                body=body.decode("utf-8", errors="replace"))
    replay = Response(content=body, status_code=response.status_code)
    replay.raw_headers = list(response.raw_headers)
    return replay


def _finalize(request: Request, response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    user = request.state.user
    sets_session = any(key == b"set-cookie" and value.startswith(SESSION_PREFIX)
                       for key, value in response.raw_headers)
    if user and request.url.path != "/api/auth/logout" and not sets_session:
        # 滑动续期：有效期内每次访问都把登录态续到 5 天后。
        response.set_cookie(auth.SESSION_COOKIE, auth.session_cookie_value(user),
                            max_age=Settings.LOGIN_SESSION_SECONDS, path="/", httponly=True, samesite="lax",
                            secure=Settings.APP_BASE_URL.startswith("https://"))
    if request.state.new_visitor:
        response.set_cookie(auth.VISITOR_COOKIE, request.state.new_visitor, max_age=Settings.VISITOR_COOKIE_SECONDS,
                            path="/", httponly=True, samesite="lax",
                            secure=Settings.APP_BASE_URL.startswith("https://"))
    return response


@app.middleware("http")
async def context_middleware(request: Request, call_next):
    request.state.user = auth.user_from_cookie(request.cookies.get(auth.SESSION_COOKIE))
    request.state.visitor = None
    request.state.new_visitor = None
    request.state.payment_log_id = None
    try:
        _guard(request)
    except APIError as exc:
        return _finalize(request, bad(exc.message, exc.code))
    audited = request.url.path in AUDITED_PATHS
    if audited:
        request.state.payment_log_id = secrets.token_hex(12)
        payment_log("inbound.request", exchange_id=request.state.payment_log_id, method=request.method,
                    url=_raw_url(request), headers=_header_lists(request.headers.items()))
        if request.method == "POST":
            payment_log("inbound.body", exchange_id=request.state.payment_log_id,
                        body=(await request.body()).decode("utf-8", errors="replace"))
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("请求处理失败 %s %s", request.method, request.url.path)
        response = bad("服务暂不可用，请稍后查看状态", 500)
    if audited:
        response = await _capture(request, response)
    logger.info('"%s %s" %s', request.method, redact(_raw_url(request)), response.status_code)
    return _finalize(request, response)
