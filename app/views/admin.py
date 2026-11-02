from __future__ import annotations

from fastapi import APIRouter, Request

from app.service import admin, auth, catalog, checkin
from app.utils.exceptions import APIError
from app.utils.result import good
from app.views._common import current_user, json_body

router = APIRouter(prefix="/api")


def _admin(request: Request) -> None:
    auth.require_admin(current_user(request))


@router.get("/admin")
async def overview(request: Request):
    _admin(request)
    return good(await admin.overview(current_user(request)))


@router.get("/admin/users")
async def users(request: Request):
    _admin(request)
    queries = request.query_params.getlist("q")
    if len(queries) != 1:
        raise APIError("请输入用户名或用户 ID")
    return good({"users": await admin.search_users(queries[0])})


@router.post("/admin/open")
async def open_today(request: Request):
    await json_body(request)
    _admin(request)
    await checkin.open_today("manual")
    return good()


@router.post("/admin/settings")
async def save_settings(request: Request):
    body = await json_body(request)
    _admin(request)
    if "reward_tiers" in body:
        auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    await checkin.save_settings(body)
    return good()


@router.post("/admin/review")
async def approve_review(request: Request):
    body = await json_body(request)
    _admin(request)
    await admin.approve_review(body)
    return good()


@router.post("/admin/points/add")
async def add_points(request: Request):
    body = await json_body(request)
    _admin(request)
    return good(await admin.add_points(body))


@router.post("/admin/products")
async def save_product(request: Request):
    body = await json_body(request)
    _admin(request)
    auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    return good({"product": await catalog.save(body)})


@router.post("/admin/products/{product_id}/archive")
async def archive_product(product_id: str, request: Request):
    body = await json_body(request)
    _admin(request)
    auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    await catalog.archive(product_id)
    return good()


@router.post("/admin/purchases/{order_no}/reconcile")
async def reconcile_purchase(order_no: str, request: Request):
    body = await json_body(request)
    _admin(request)
    auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    return good({"order": await catalog.reconcile(order_no, body.get("result"), body.get("trade_no"))})


@router.post("/trigger/open")
async def trigger_open(request: Request):
    await json_body(request)
    auth.require_trigger(request.headers.get("X-Trigger-Token"))
    await checkin.open_today("trigger")
    return good()
