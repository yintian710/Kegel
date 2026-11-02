from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.config import ROOT
from app.utils.exceptions import APIError

router = APIRouter(prefix="/api")

IMG_DIR = ROOT / "app" / "assets" / "img"
ICON_SIZES = {"16", "32", "48", "64", "128", "180", "192", "256", "512", "1024"}


@router.get("/icon")
async def icon(size: list[str] | None = Query(default=None)):
    if size is None:
        return FileResponse(IMG_DIR / "icon.png")
    if len(size) != 1 or size[0] not in ICON_SIZES:
        raise APIError("size 仅支持 16、32、48、64、128、180、192、256、512、1024")
    return FileResponse(IMG_DIR / f"icon-{size[0]}.png")
