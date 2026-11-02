from __future__ import annotations

from fastapi import APIRouter, Request

from app.service import auth, checkin
from app.utils import timeutil
from app.utils.result import good
from app.views._common import client_ip, current_user, json_body, visitor_of

router = APIRouter(prefix="/api")


@router.get("/status")
async def status(request: Request):
    user = current_user(request)
    identity = auth.practice_identity(user, visitor_of(request))
    return good(await checkin.status_view(user, timeutil.now(), identity["id"]))


@router.post("/visit")
async def visit(request: Request):
    await json_body(request)
    return good(await checkin.visit(current_user(request), visitor_of(request), client_ip(request)))


@router.post("/session/start")
async def session_start(request: Request):
    body = await json_body(request)
    return good(await checkin.start_session(current_user(request), visitor_of(request), client_ip(request), body))


@router.post("/session/step")
async def session_step(request: Request):
    body = await json_body(request)
    return good(await checkin.advance_session(current_user(request), visitor_of(request), client_ip(request), body))


@router.post("/session/complete")
async def session_complete(request: Request):
    body = await json_body(request)
    return good(await checkin.complete_session(current_user(request), visitor_of(request), body))


@router.post("/claim")
async def claim(request: Request):
    await json_body(request)
    return good(await checkin.claim(auth.require_user(current_user(request))))
