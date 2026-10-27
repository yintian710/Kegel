from __future__ import annotations

import re
import secrets
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import credits

_AMOUNT_RE = re.compile(r"^(0|[1-9][0-9]{0,4})(?:\.([0-9]{1,2}))?$")


def init_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS shop_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL DEFAULT 'LDC',
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        points_price INTEGER NOT NULL CHECK(points_price >= 0),
        ldc_amount TEXT NOT NULL DEFAULT '1.00',
        user_daily_limit INTEGER NOT NULL DEFAULT 0 CHECK(user_daily_limit >= 0),
        total_daily_limit INTEGER NOT NULL DEFAULT 0 CHECK(total_daily_limit >= 0),
        is_active INTEGER NOT NULL CHECK(is_active IN (0,1))
    )""")
    # Check if migration needed
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(shop_products)")}
    if "category" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN category TEXT NOT NULL DEFAULT 'LDC'")
    if "ldc_amount" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN ldc_amount TEXT NOT NULL DEFAULT '1.00'")
    if "user_daily_limit" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN user_daily_limit INTEGER NOT NULL DEFAULT 0")
    if "total_daily_limit" not in columns:
        connection.execute("ALTER TABLE shop_products ADD COLUMN total_daily_limit INTEGER NOT NULL DEFAULT 0")

    connection.execute("""CREATE TABLE IF NOT EXISTS shop_purchases (
        order_no TEXT PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES shop_products(id),
        category TEXT NOT NULL,
        product_name TEXT NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT NOT NULL,
        points_cost INTEGER NOT NULL,
        ldc_amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'success', 'simulated', 'failed', 'uncertain')),
        trade_no TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        day TEXT NOT NULL
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS shop_purchases_user ON shop_purchases(user_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS shop_purchases_day ON shop_purchases(day, product_id)")


def parse_ldc_amount(value: Any) -> str:
    raw = str(value).strip() if value is not None else ""
    if not _AMOUNT_RE.fullmatch(raw):
        raise ValueError("LDC 数量格式错误，必须为 0.01 至 10000.00 的有效金额")
    try:
        dec = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError("LDC 数量必须为有效金额") from None
    if dec <= Decimal("0") or dec > Decimal("10000"):
        raise ValueError("LDC 数量必须在 0.01 到 10000 之间")
    return f"{dec:.2f}"


def product_view(row: sqlite3.Row, user_id: str | None = None, today: str = "", connection: sqlite3.Connection | None = None) -> dict:
    result = dict(row)
    result["is_active"] = bool(row["is_active"])
    result["user_daily_limit"] = int(row["user_daily_limit"])
    result["total_daily_limit"] = int(row["total_daily_limit"])

    if connection and today:
        pid = row["id"]
        # Total bought today
        total_bought = connection.execute(
            "SELECT COUNT(*) FROM shop_purchases WHERE day=? AND product_id=? AND status IN ('pending', 'success', 'simulated', 'uncertain')",
            (today, pid)
        ).fetchone()[0]
        result["total_today_count"] = total_bought
        result["total_remaining"] = max(0, result["total_daily_limit"] - total_bought) if result["total_daily_limit"] > 0 else None

        # User bought today
        if user_id:
            user_bought = connection.execute(
                "SELECT COUNT(*) FROM shop_purchases WHERE day=? AND product_id=? AND user_id=? AND status IN ('pending', 'success', 'simulated', 'uncertain')",
                (today, pid, user_id)
            ).fetchone()[0]
            result["user_today_count"] = user_bought
            result["user_remaining"] = max(0, result["user_daily_limit"] - user_bought) if result["user_daily_limit"] > 0 else None
        else:
            result["user_today_count"] = 0
            result["user_remaining"] = result["user_daily_limit"] if result["user_daily_limit"] > 0 else None
    else:
        result["total_today_count"] = 0
        result["total_remaining"] = None
        result["user_today_count"] = 0
        result["user_remaining"] = None

    return result


def list_products(connection: sqlite3.Connection, *, user_id: str | None = None, today: str = "", include_inactive: bool = False) -> list[dict]:
    query = "SELECT * FROM shop_products"
    if not include_inactive:
        query += " WHERE is_active=1"
    rows = connection.execute(query + " ORDER BY id DESC").fetchall()
    return [product_view(row, user_id, today, connection) for row in rows]


def save(connection: sqlite3.Connection, body: dict) -> dict:
    allowed = {"id", "category", "name", "description", "points_price", "ldc_amount", "user_daily_limit", "total_daily_limit", "is_active"}
    if set(body) - allowed:
        raise ValueError("包含不支持的商品字段")
    category = str(body.get("category", "LDC")).strip()
    if category != "LDC":
        raise ValueError("目前仅支持 LDC 品类商品")
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("商品名称需为 1–80 字")
    description = body.get("description", "")
    if not isinstance(description, str) or len(description.strip()) > 500:
        raise ValueError("商品介绍不可超过 500 字")
    price = credits.parse_points(body.get("points_price"))
    ldc_amount = parse_ldc_amount(body.get("ldc_amount", "1.00"))
    user_daily_limit = int(body.get("user_daily_limit", 0))
    if user_daily_limit < 0 or user_daily_limit > 100000:
        raise ValueError("单人每日限购须为 0–100000 的整数 (0为不限)")
    total_daily_limit = int(body.get("total_daily_limit", 0))
    if total_daily_limit < 0 or total_daily_limit > 100000:
        raise ValueError("全站每日限购须为 0–100000 的整数 (0为不限)")
    active = body.get("is_active")
    if type(active) is not bool:
        raise ValueError("需指定商品是否上架")

    values = (category, name.strip(), description.strip(), price, ldc_amount, user_daily_limit, total_daily_limit, int(active))
    product_id = body.get("id")
    if product_id is None:
        product_id = connection.execute("""INSERT INTO shop_products
            (category, name, description, points_price, ldc_amount, user_daily_limit, total_daily_limit, is_active)
            VALUES (?,?,?,?,?,?,?,?)""", values).lastrowid
    else:
        if type(product_id) is not int or product_id < 1:
            raise ValueError("商品编号不正确")
        changed = connection.execute("""UPDATE shop_products SET
            category=?, name=?, description=?, points_price=?, ldc_amount=?, user_daily_limit=?, total_daily_limit=?, is_active=?
            WHERE id=?""", (*values, product_id)).rowcount
        if not changed:
            raise ValueError("商品不存在")
    return product_view(connection.execute("SELECT * FROM shop_products WHERE id=?", (product_id,)).fetchone())


def archive(connection: sqlite3.Connection, product_id: int) -> None:
    if product_id < 1 or not connection.execute("UPDATE shop_products SET is_active=0 WHERE id=?", (product_id,)).rowcount:
        raise ValueError("商品不存在")


def purchase_view(row: sqlite3.Row, tz: Any) -> dict:
    result = dict(row)
    result["created_at"] = datetime.fromtimestamp(row["created_at"], tz).isoformat(timespec="seconds")
    return result


def user_purchases(connection: sqlite3.Connection, user_id: str, tz: Any) -> list[dict]:
    rows = connection.execute("SELECT * FROM shop_purchases WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user_id,)).fetchall()
    return [purchase_view(row, tz) for row in rows]


def all_purchases(connection: sqlite3.Connection, tz: Any) -> list[dict]:
    rows = connection.execute("SELECT * FROM shop_purchases ORDER BY created_at DESC LIMIT 200").fetchall()
    return [purchase_view(row, tz) for row in rows]


def daily_ldc_used(connection: sqlite3.Connection, today: str) -> Decimal:
    row = connection.execute("""SELECT COALESCE(SUM(
        CAST(ldc_amount AS INTEGER) * 100 +
        CAST(substr(ldc_amount, instr(ldc_amount, '.') + 1) AS INTEGER)
        ), 0) FROM shop_purchases
        WHERE day=? AND status IN ('pending', 'success', 'simulated', 'uncertain')""", (today,)).fetchone()
    return Decimal(row[0]) / 100


def purchase_product(
    connection: sqlite3.Connection,
    user: dict,
    product_id: int,
    today: str,
    now: float,
    dispatch_fn: Callable[[str, dict, str], tuple[str, str, str]],
    *,
    daily_ldc_limit: int,
) -> dict:
    """
    Executes a purchase of an LDC product with auto delivery.
    Caller manages database transaction.
    """
    if not connection.in_transaction:
        raise RuntimeError("购买商品必须处于写事务内")

    product = connection.execute("SELECT * FROM shop_products WHERE id=?", (product_id,)).fetchone()
    if not product or not product["is_active"]:
        raise ValueError("商品不存在或已下架")

    pid = product["id"]
    points_cost = product["points_price"]
    ldc_amount = product["ldc_amount"]
    user_daily_limit = product["user_daily_limit"]
    total_daily_limit = product["total_daily_limit"]

    # Check limits
    if total_daily_limit > 0:
        total_bought = connection.execute(
            "SELECT COUNT(*) FROM shop_purchases WHERE day=? AND product_id=? AND status IN ('pending', 'success', 'simulated', 'uncertain')",
            (today, pid)
        ).fetchone()[0]
        if total_bought >= total_daily_limit:
            raise ValueError(f"今日全站兑换限额已满（限额 {total_daily_limit} 份/天）")

    if user_daily_limit > 0:
        user_bought = connection.execute(
            "SELECT COUNT(*) FROM shop_purchases WHERE day=? AND product_id=? AND user_id=? AND status IN ('pending', 'success', 'simulated', 'uncertain')",
            (today, pid, user["id"])
        ).fetchone()[0]
        if user_bought >= user_daily_limit:
            raise ValueError(f"今日已达单人兑换限额（限额 {user_daily_limit} 份/天）")

    remaining = max(Decimal(0), Decimal(daily_ldc_limit) - daily_ldc_used(connection, today))
    if Decimal(ldc_amount) > remaining:
        raise ValueError(f"今日全站 LDC 兑换额度不足：剩余 {remaining:.2f} LDC，本次兑换 {ldc_amount} LDC；不支持拆分兑换")

    order_no = f"SO-{today.replace('-', '')}-{secrets.token_hex(6).upper()}"

    # Deduct points from user's wallet
    credits.spend_points(connection, user, points_cost, "shop_purchase", order_no, now)

    # Insert pending purchase order
    connection.execute("""INSERT INTO shop_purchases
        (order_no, product_id, category, product_name, user_id, username, points_cost, ldc_amount, status, created_at, day)
        VALUES (?,?,?,?,?,?,?,?,'pending',?,?)""",
        (order_no, pid, product["category"], product["name"], user["id"], user["username"], points_cost, ldc_amount, now, today))

    # Auto dispatch LDC to user's account
    status, trade_no, error = dispatch_fn(order_no, user, ldc_amount)

    if status in ("success", "simulated"):
        connection.execute(
            "UPDATE shop_purchases SET status=?, trade_no=? WHERE order_no=?",
            (status, trade_no, order_no)
        )
    elif status == "failed":
        # Delivery failed! Refund user points
        credits.refund_points(connection, user, points_cost, "shop_refund", f"refund:{order_no}", now)
        connection.execute(
            "UPDATE shop_purchases SET status='failed', error=? WHERE order_no=?",
            (error[:300], order_no)
        )
    else:  # uncertain
        connection.execute(
            "UPDATE shop_purchases SET status='uncertain', error=? WHERE order_no=?",
            (error[:300], order_no)
        )

    order = connection.execute("SELECT * FROM shop_purchases WHERE order_no=?", (order_no,)).fetchone()
    return {
        "order": dict(order),
        "status": status,
        "trade_no": trade_no,
        "error": error
    }
