from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.common.payment_log import payment_log
from app.config import Settings
from app.service import auth, donations
from app.utils import timeutil
from app.utils.result import good
from app.views._common import current_user, json_body

router = APIRouter(prefix="/api")


@router.get("/donations")
async def donation_page(request: Request):
    user = current_user(request)
    auth.require_login_if_configured(user)
    return good({"user": user, "oauth_ready": Settings.oauth_ready(), **await donations.shop_data(user)})


@router.post("/donations/create")
async def create_donation(request: Request):
    body = await json_body(request)
    user = auth.require_user(current_user(request))
    return good(await donations.create_order(user, body.get("amount"), timeutil.now()))


@router.get("/payments/ldc/notify")
async def ldc_notify(request: Request):
    """Provider callback: plain-text success/fail, never the JSON envelope."""
    exchange_id = getattr(request.state, "payment_log_id", None)
    query: dict[str, list[str]] = {}
    try:
        query = parse_qs(request.url.query, keep_blank_values=True, max_num_fields=30)
        if any(len(values) != 1 for values in query.values()):
            raise ValueError("重复的通知字段")
        await donations.accept_notification({key: values[0] for key, values in query.items()}, timeutil.now())
    except ValueError as exc:
        payment_log("callback.rejected", exchange_id=exchange_id, reason=str(exc))
        return PlainTextResponse("fail", status_code=400)
    except Exception as exc:
        payment_log("callback.error", exchange_id=exchange_id, error_type=type(exc).__name__, reason=str(exc))
        raise
    payment_log("callback.accepted", exchange_id=exchange_id,
                out_trade_no=query.get("out_trade_no"), trade_no=query.get("trade_no"))
    return PlainTextResponse("success")
