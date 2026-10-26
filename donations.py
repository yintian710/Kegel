from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_AMOUNT_CENTS = 1_000_000
ORDER_NAME = "LDC 赞助"
_ORDER_PATTERN = re.compile(r"LDC[0-9a-f]{32}")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
_AMOUNT_PATTERN = re.compile(r"(0|[1-9][0-9]{0,4})(?:\.([0-9]{1,2}))?")
_CALLBACK_FIELDS = frozenset({
    "pid", "trade_no", "out_trade_no", "type", "name", "money", "trade_status", "sign",
})


def init_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS donation_orders (
        order_no TEXT PRIMARY KEY, user_id TEXT NOT NULL, username TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0 AND amount_cents <= 1000000),
        pid TEXT NOT NULL, name TEXT NOT NULL, created_at REAL NOT NULL
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS donation_settlements (
        order_no TEXT PRIMARY KEY REFERENCES donation_orders(order_no),
        trade_no TEXT NOT NULL UNIQUE, paid_at REAL NOT NULL
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS donation_orders_user ON donation_orders(user_id,created_at)")


def _credentials() -> tuple[str, str]:
    pid = os.environ.get("LDC_CLIENT_ID", "")
    secret = os.environ.get("LDC_CLIENT_SECRET", "")
    if (not _IDENTIFIER_PATTERN.fullmatch(pid) or not secret or len(secret) > 4096
            or secret != secret.strip() or any(ord(char) < 32 or ord(char) == 127 for char in secret)):
        raise ValueError("LDC 商户凭据未配置或无效")
    return pid, secret


def _base_url(value: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 2048
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
            or "\\" in value or "?" in value or "#" in value):
        raise ValueError("LDC 及站点地址必须是有效的 HTTPS URL")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (not host or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or (port is not None and not 1 <= port <= 65535)):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if (len(host) > 253 or not all(
                    re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                    for label in host.split("."))):
                raise ValueError
        if parsed.scheme != "https" and not (
                parsed.scheme == "http" and host in {"localhost", "127.0.0.1"}):
            raise ValueError
    except ValueError:
        raise ValueError("LDC 及站点地址必须是 HTTPS；仅本地 localhost/127.0.0.1 允许 HTTP") from None
    return value.rstrip("/")


def _payment_config(base_url: str) -> tuple[str, str, str, str]:
    if os.environ.get("LDC_DONATION_ENABLED", "false").lower() != "true":
        raise ValueError("LDC 赞助暂未启用")
    pid, secret = _credentials()
    api_base = _base_url(os.environ.get("LDC_API_BASE", "https://credit.linux.do"))
    site_base = _base_url(base_url)
    notify_url = site_base + "/payments/ldc/notify"
    return_prefix = site_base + "/donate?donation="
    if len(notify_url) > 100 or len(return_prefix) + 35 > 100:
        raise ValueError("LDC 通知及回跳 URL 不可超过 100 字符")
    return pid, secret, api_base + "/epay/pay/submit.php", site_base


def _amount_cents(value: str) -> int:
    match = _AMOUNT_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError("赞助金额须为 0.01–10000.00 的十进制字符串，最多两位小数")
    cents = int(match[1]) * 100 + int((match[2] or "").ljust(2, "0"))
    if not 1 <= cents <= MAX_AMOUNT_CENTS:
        raise ValueError("赞助金额须为 0.01–10000.00")
    return cents


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _sign(fields: dict[str, str], secret: str) -> str:
    payload = "&".join(f"{key}={value}" for key, value in sorted(fields.items())
                       if key not in {"sign", "sign_type"} and value != "")
    return hashlib.md5((payload + secret).encode("utf-8")).hexdigest()


def _iso(timestamp: float | None) -> str | None:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds") if timestamp is not None else None


def _order_view(row: sqlite3.Row) -> dict:
    return {"order_no": row["order_no"], "amount": _money(row["amount_cents"]),
            "status": "paid" if row["paid_at"] is not None else "created",
            "created_at": _iso(row["created_at"]), "paid_at": _iso(row["paid_at"])}


def shop_data(connection: sqlite3.Connection, user: dict | None, base_url: str) -> dict:
    try:
        _payment_config(base_url)
        ready = True
    except ValueError:
        ready = False
    rows = connection.execute("""WITH totals AS (
        SELECT orders.user_id, SUM(orders.amount_cents) AS amount_cents,
               COUNT(*) AS count, MIN(settlements.paid_at) AS first_paid
        FROM donation_orders AS orders JOIN donation_settlements AS settlements USING(order_no)
        GROUP BY orders.user_id
    ) SELECT totals.*, (
        SELECT orders.username FROM donation_orders AS orders
        JOIN donation_settlements AS settlements USING(order_no)
        WHERE orders.user_id=totals.user_id
        ORDER BY settlements.paid_at DESC, orders.order_no DESC LIMIT 1
    ) AS username FROM totals
    ORDER BY amount_cents DESC, first_paid, user_id LIMIT 50""")
    leaderboard = [{"rank": rank, "username": row["username"], "amount": _money(row["amount_cents"]),
                    "count": row["count"]} for rank, row in enumerate(rows, 1)]
    orders = []
    if user:
        orders = [_order_view(row) for row in connection.execute("""
            SELECT orders.*, settlements.paid_at FROM donation_orders AS orders
            LEFT JOIN donation_settlements AS settlements USING(order_no)
            WHERE orders.user_id=? ORDER BY orders.created_at DESC, orders.order_no DESC LIMIT 20
        """, (user["id"],))]
    return {"donation_ready": ready, "donation_leaderboard": leaderboard, "donation_orders": orders}


def create_order(connection: sqlite3.Connection, user: dict, amount: str, base_url: str, now: float) -> dict:
    """Caller holds BEGIN IMMEDIATE; orders never modify station points."""
    if not connection.in_transaction:
        raise RuntimeError("创建赞助订单必须处于写事务内")
    pid, secret, action, site_base = _payment_config(base_url)
    if not isinstance(user, dict) or any(
            not isinstance(user.get(key), str) or not user[key] or len(user[key]) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in user[key])
            for key in ("id", "username")):
        raise ValueError("赞助需要有效的 OAuth 用户身份")
    cents = _amount_cents(amount)
    order_no = "LDC" + secrets.token_hex(16)
    fields = {"pid": pid, "type": "epay", "out_trade_no": order_no, "name": ORDER_NAME,
              "money": _money(cents), "notify_url": site_base + "/payments/ldc/notify",
              "return_url": site_base + "/donate?donation=" + order_no}
    fields["sign"] = _sign(fields, secret)
    fields["sign_type"] = "MD5"
    try:
        connection.execute("""INSERT INTO donation_orders
            (order_no,user_id,username,amount_cents,pid,name,created_at) VALUES (?,?,?,?,?,?,?)
        """, (order_no, user["id"], user["username"], cents, pid, ORDER_NAME, now))
    except sqlite3.IntegrityError:
        raise ValueError("赞助订单号冲突，请重新创建") from None
    order = {"order_no": order_no, "amount": _money(cents), "status": "created",
             "created_at": _iso(now), "paid_at": None}
    return {"order": order, "payment": {"action": action, "fields": fields}}


def accept_notification(connection: sqlite3.Connection, params: dict[str, str], now: float) -> None:
    """Verify provider evidence and append one settlement inside the caller's write transaction."""
    if not connection.in_transaction:
        raise RuntimeError("赞助结算必须处于写事务内")
    pid, secret = _credentials()
    if (not isinstance(params, dict) or not _CALLBACK_FIELDS.issubset(params)
            or set(params) - _CALLBACK_FIELDS - {"sign_type"}
            or any(not isinstance(value, str) or not value or len(value) > 256 for value in params.values())):
        raise ValueError("LDC 通知字段缺失或无效")
    if (params.get("sign_type", "MD5") != "MD5" or params["pid"] != pid
            or params["type"] != "epay" or params["trade_status"] != "TRADE_SUCCESS"
            or not _ORDER_PATTERN.fullmatch(params["out_trade_no"])
            or not _IDENTIFIER_PATTERN.fullmatch(params["trade_no"])
            or not re.fullmatch(r"[0-9a-f]{32}", params["sign"])):
        raise ValueError("LDC 通知商户、订单、状态或签名格式无效")
    if not hmac.compare_digest(params["sign"], _sign(params, secret)):
        raise ValueError("LDC 通知签名无效")
    cents = _amount_cents(params["money"])
    order = connection.execute("SELECT * FROM donation_orders WHERE order_no=?", (params["out_trade_no"],)).fetchone()
    if (not order or order["pid"] != params["pid"] or order["amount_cents"] != cents
            or order["name"] != params["name"]):
        raise ValueError("LDC 通知与赞助订单不匹配")
    settled = connection.execute("SELECT trade_no FROM donation_settlements WHERE order_no=?", (order["order_no"],)).fetchone()
    if settled:
        if settled["trade_no"] != params["trade_no"]:
            raise ValueError("赞助订单已由其他交易结算")
        return
    try:
        connection.execute("INSERT INTO donation_settlements(order_no,trade_no,paid_at) VALUES (?,?,?)",
                           (order["order_no"], params["trade_no"], now))
    except sqlite3.IntegrityError:
        raise ValueError("LDC 交易已用于其他赞助订单") from None
