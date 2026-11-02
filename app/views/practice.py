from __future__ import annotations

from fastapi import APIRouter, Request

from app.service import auth, checkin
from app.utils import timeutil
from app.utils.result import good
from app.views._common import current_user, json_body

router = APIRouter(prefix="/api/practice")


@router.get("")
async def practice(request: Request):
    return good(await checkin.practice_api_view(current_user(request), timeutil.day_key()))


@router.post("/records")
async def upload_record(request: Request):
    body = await json_body(request)
    return good(await checkin.upload_training_record(auth.require_user(current_user(request)), body))
