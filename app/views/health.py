from __future__ import annotations

from fastapi import APIRouter

from app.utils.result import good

router = APIRouter()


@router.get("/health")
async def health():
    return good({"status": "ok"})


@router.get("/api/heartbeat")
async def heartbeat():
    return good()
