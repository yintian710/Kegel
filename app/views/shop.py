from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import Settings
from app.service import auth, catalog, credits
from app.utils import timeutil
from app.utils.result import good
from app.views._common import current_user, json_body

router = APIRouter(prefix="/api/shop")


@router.get("")
async def shop(request: Request):
    user = current_user(request)
    auth.require_login_if_configured(user)
    today = timeutil.day_key()
    uid = user["id"] if user else None
    return good({"user": user, "oauth_ready": Settings.oauth_ready(),
                 "wallet": await credits.wallet_view(uid) if user else None,
                 "quota": await catalog.quota_view(today),
                 "ledger": await credits.ledger_view(uid) if user else [],
                 "products": await catalog.list_products(user_id=uid, today=today),
                 "purchases": await catalog.user_purchases(uid) if user else []})


@router.post("/purchase")
async def purchase(request: Request):
    body = await json_body(request)
    user = auth.require_user(current_user(request))
    return good(await catalog.purchase_product(user, body.get("product_id"), body.get("request_id")))
