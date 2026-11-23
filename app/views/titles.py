from __future__ import annotations

from fastapi import APIRouter, Request

from app.service import auth, titles
from app.utils.exceptions import APIError
from app.utils.result import good
from app.views._common import current_user, json_body

router = APIRouter(prefix="/api")


def _admin(request: Request) -> None:
    auth.require_admin(current_user(request))


# ── 用户端 ─────────────────────────────────────────────────────────────────────

@router.get("/titles")
async def title_home(request: Request):
    user = current_user(request)
    auth.require_login_if_configured(user)
    return good(await titles.title_view(user))


@router.post("/titles/draw")
async def draw(request: Request):
    body = await json_body(request)
    return good(await titles.draw(auth.require_user(current_user(request)), body))


@router.post("/titles/tickets/purchase")
async def purchase_ticket(request: Request):
    body = await json_body(request)
    return good(await titles.purchase_ticket(auth.require_user(current_user(request)), body))


@router.post("/titles/equip")
async def equip(request: Request):
    body = await json_body(request)
    return good(await titles.equip(auth.require_user(current_user(request)), body))


@router.post("/titles/smelt")
async def smelt(request: Request):
    body = await json_body(request)
    return good(await titles.smelt(auth.require_user(current_user(request)), body))


@router.post("/titles/craft")
async def craft(request: Request):
    body = await json_body(request)
    return good(await titles.craft_ur(auth.require_user(current_user(request)), body))


@router.get("/titles/history")
async def history(request: Request):
    user = auth.require_user(current_user(request))
    return good(await titles.history(user["id"]))


# ── 管理端 ─────────────────────────────────────────────────────────────────────

@router.get("/admin/titles")
async def admin_titles(request: Request):
    _admin(request)
    return good(await titles.admin_list())


@router.post("/admin/titles")
async def admin_save_title(request: Request):
    body = await json_body(request)
    _admin(request)
    auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    return good(await titles.admin_save(body))


@router.post("/admin/titles/grant")
async def admin_grant_title(request: Request):
    body = await json_body(request)
    _admin(request)
    auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    return good(await titles.admin_grant(body))


@router.get("/admin/titles/stats")
async def admin_title_stats(request: Request):
    _admin(request)
    return good(await titles.admin_stats())


@router.post("/admin/titles/config")
async def admin_title_config(request: Request):
    body = await json_body(request)
    _admin(request)
    auth.verify_secondary_secret(auth.secondary_secret_from(body, request.headers))
    return good(await titles.admin_save_config(body))
