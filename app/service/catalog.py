from __future__ import annotations

import re
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any

from app.common.linuxdo import dispatch_ldc
from app.config import Settings
from app.infrastructure.database import execute, fetch, fetch_one, write_txn
from app.infrastructure.database.schemas import ShopProduct, ShopPurchase
from app.service import credits
from app.utils import timeutil
from app.utils.exceptions import APIError

_AMOUNT_RE = re.compile(r"^(0|[1-9][0-9]{0,4})(?:\.([0-9]{1,2}))?$")
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_HOLDING = "('pending', 'success', 'simulated', 'uncertain')"
_PRODUCT_FIELDS = {"id", "category", "name", "description", "points_price", "ldc_amount", "user_daily_limit",
                   "total_daily_limit", "is_active", "secondary_secret", "secondary_password"}


def parse_ldc_amount(value: Any) -> str:
    raw = str(value).strip() if value is not None else ""
    if not _AMOUNT_RE.fullmatch(raw):
        raise APIError("LDC 数量格式错误，必须为 0.01 至 10000.00 的有效金额")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise APIError("LDC 数量必须为有效金额") from None
    if amount <= Decimal("0") or amount > Decimal("10000"):
        raise APIError("LDC 数量必须在 0.01 到 10000 之间")
    return f"{amount:.2f}"


def _product_view(row: dict, total_bought: int | None = None, user_bought: int | None = None) -> dict:
    result = dict(row)
    result["is_active"] = bool(row["is_active"])
    total_limit, user_limit = int(row["total_daily_limit"]), int(row["user_daily_limit"])
    if total_bought is None:
        result.update(total_today_count=0, total_remaining=None, user_today_count=0, user_remaining=None)
        return result
    user_bought = user_bought or 0
    result["total_today_count"] = total_bought
    result["total_remaining"] = max(0, total_limit - total_bought) if total_limit > 0 else None
    result["user_today_count"] = user_bought
    result["user_remaining"] = max(0, user_limit - user_bought) if user_limit > 0 else None
    return result


async def list_products(*, user_id: str | None = None, today: str = "", include_inactive: bool = False) -> list[dict]:
    rows = await fetch("SELECT * FROM shop_products" + ("" if include_inactive else " WHERE is_active=1")
                       + " ORDER BY id DESC")
    if not today:
        return [_product_view(row) for row in rows]
    totals = {row["product_id"]: row["n"] for row in await fetch(
        f"SELECT product_id,COUNT(*) AS n FROM shop_purchases WHERE day=$1 AND status IN {_HOLDING} "
        "GROUP BY product_id", today)}
    mine = {} if not user_id else {row["product_id"]: row["n"] for row in await fetch(
        f"SELECT product_id,COUNT(*) AS n FROM shop_purchases WHERE day=$1 AND user_id=$2 AND status IN {_HOLDING} "
        "GROUP BY product_id", today, user_id)}
    return [_product_view(row, totals.get(row["id"], 0), mine.get(row["id"], 0)) for row in rows]


def _limit(body: dict, key: str, label: str) -> int:
    try:
        value = int(body.get(key, 0))
    except (TypeError, ValueError):
        raise APIError(f"{label}须为 0–100000 的整数 (0为不限)") from None
    if not 0 <= value <= 100000:
        raise APIError(f"{label}须为 0–100000 的整数 (0为不限)")
    return value


def _product_id(value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or value < 1:
        raise APIError("商品编号不正确")
    return value


async def save(body: dict) -> dict:
    """Create or update a product."""
    if set(body) - _PRODUCT_FIELDS:
        raise APIError("包含不支持的商品字段")
    category = str(body.get("category", "LDC")).strip()
    if category != "LDC":
        raise APIError("目前仅支持 LDC 品类商品")
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise APIError("商品名称需为 1–80 字")
    description = body.get("description", "")
    if not isinstance(description, str) or len(description.strip()) > 500:
        raise APIError("商品介绍不可超过 500 字")
    try:
        price = credits.parse_points(body.get("points_price"))
    except ValueError as exc:
        raise APIError(str(exc)) from None
    ldc_amount = parse_ldc_amount(body.get("ldc_amount", "1.00"))
    user_limit = _limit(body, "user_daily_limit", "单人每日限购")
    total_limit = _limit(body, "total_daily_limit", "全站每日限购")
    active = body.get("is_active")
    if type(active) is not bool:
        raise APIError("需指定商品是否上架")
    values = {"category": category, "name": name.strip(), "description": description.strip(), "points_price": price,
              "ldc_amount": ldc_amount, "user_daily_limit": user_limit, "total_daily_limit": total_limit,
              "is_active": int(active)}
    async with write_txn():
        if body.get("id") is None:
            product_id = (await ShopProduct.create(**values)).id
        else:
            product_id = _product_id(body["id"])
            if not await ShopProduct.filter(id=product_id).update(**values):
                raise APIError("商品不存在", 404)
        row = await fetch_one("SELECT * FROM shop_products WHERE id=$1", product_id)
    return _product_view(row)


async def archive(product_id: Any) -> None:
    if not await ShopProduct.filter(id=_product_id(product_id)).update(is_active=0):
        raise APIError("商品不存在", 404)


def _purchase_views(rows: list[dict]) -> list[dict]:
    return [{**row, "created_at": timeutil.iso_time(row["created_at"])} for row in rows]


async def user_purchases(user_id: str) -> list[dict]:
    return _purchase_views(await fetch(
        "SELECT * FROM shop_purchases WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user_id))


async def all_purchases() -> list[dict]:
    return _purchase_views(await fetch("SELECT * FROM shop_purchases ORDER BY created_at DESC LIMIT 200"))


async def daily_ldc_used(today: str) -> Decimal:
    row = await fetch_one(
        f"SELECT COALESCE(SUM(ROUND(ldc_amount::numeric * 100)), 0) AS cents FROM shop_purchases "
        f"WHERE day=$1 AND status IN {_HOLDING}", today)
    return Decimal(row["cents"]) / 100


async def quota_view(today: str) -> dict[str, str]:
    limit = Settings.DAILY_LDC_LIMIT
    used = await daily_ldc_used(today)
    return {"limit": f"{limit:.2f}", "used": f"{used:.2f}",
            "remaining": f"{max(Decimal(0), Decimal(limit) - used):.2f}"}


def _outcome(order: dict) -> dict:
    return {"order": order, "status": order["status"], "trade_no": order["trade_no"], "error": order["error"]}


async def _reserve(user: dict, product_id: int, today: str, now: float, request_id: str | None) -> tuple[dict, bool]:
    """Transaction 1: validate limits, debit points and persist a pending order. -> (order, is_new)."""
    async with write_txn():
        if request_id is not None:
            existing = await fetch_one("SELECT * FROM shop_purchases WHERE user_id=$1 AND request_id=$2",
                                       user["id"], request_id)
            if existing:
                if existing["product_id"] != product_id:
                    raise ValueError("兑换请求编号已用于其他商品")
                return existing, False
        product = await fetch_one("SELECT * FROM shop_products WHERE id=$1", product_id)
        if not product or not product["is_active"]:
            raise APIError("商品不存在或已下架", 404)
        total_limit, user_limit = product["total_daily_limit"], product["user_daily_limit"]
        if total_limit > 0:
            bought = (await fetch_one(
                f"SELECT COUNT(*) AS n FROM shop_purchases WHERE day=$1 AND product_id=$2 AND status IN {_HOLDING}",
                today, product_id))["n"]
            if bought >= total_limit:
                raise ValueError(f"今日全站兑换限额已满（限额 {total_limit} 份/天）")
        if user_limit > 0:
            bought = (await fetch_one(
                f"SELECT COUNT(*) AS n FROM shop_purchases WHERE day=$1 AND product_id=$2 AND user_id=$3 "
                f"AND status IN {_HOLDING}", today, product_id, user["id"]))["n"]
            if bought >= user_limit:
                raise ValueError(f"今日已达单人兑换限额（限额 {user_limit} 份/天）")
        remaining = max(Decimal(0), Decimal(Settings.DAILY_LDC_LIMIT) - await daily_ldc_used(today))
        if Decimal(product["ldc_amount"]) > remaining:
            raise ValueError(f"今日全站 LDC 兑换额度不足：剩余 {remaining:.2f} LDC，"
                             f"本次兑换 {product['ldc_amount']} LDC；不支持拆分兑换")
        order_no = f"SO-{today.replace('-', '')}-{secrets.token_hex(6).upper()}"
        await credits.spend_points(user, product["points_price"], "shop_purchase", order_no, now)
        await ShopPurchase.create(order_no=order_no, product_id=product_id, category=product["category"],
                                  product_name=product["name"], user_id=user["id"], username=user["username"],
                                  points_cost=product["points_price"], ldc_amount=product["ldc_amount"],
                                  status="pending", created_at=now, day=today, request_id=request_id)
        return await fetch_one("SELECT * FROM shop_purchases WHERE order_no=$1", order_no), True


async def purchase_product(user: dict, product_id: Any, request_id: Any) -> dict:
    """Redeem points for LDC. The reservation commits before delivery so a crash never loses the debit."""
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        raise APIError("请选择有效的兑换商品") from None
    if request_id is not None and (not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id)):
        raise APIError("兑换请求编号格式错误")
    now = timeutil.now()
    today = timeutil.day_key(now)
    order, is_new = await _reserve(user, product_id, today, now, request_id)
    if not is_new:
        return _outcome(order)

    status, trade_no, error = await dispatch_ldc(order["order_no"], user, order["ldc_amount"])

    async with write_txn():
        if status in ("success", "simulated"):
            await execute("UPDATE shop_purchases SET status=$1, trade_no=$2 WHERE order_no=$3",
                          status, trade_no, order["order_no"])
        elif status == "failed":
            await credits.refund_points(user, order["points_cost"], "shop_refund", f"refund:{order['order_no']}", now)
            await execute("UPDATE shop_purchases SET status='failed', error=$1 WHERE order_no=$2",
                          error[:300], order["order_no"])
        else:
            status = "uncertain"
            await execute("UPDATE shop_purchases SET status='uncertain', error=$1 WHERE order_no=$2",
                          error[:300], order["order_no"])
        final = await fetch_one("SELECT * FROM shop_purchases WHERE order_no=$1", order["order_no"])
    return {"order": final, "status": status, "trade_no": trade_no, "error": error}
