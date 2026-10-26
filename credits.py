from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

MAX_POINTS = 9_000_000_000_000_000


def init_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS points_wallets (
        user_id TEXT PRIMARY KEY, username TEXT NOT NULL,
        balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0 AND balance <= 9000000000000000)
    )""")
    # Check if points_ledger has delta > 0 constraint, migrate to delta != 0
    schema = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='points_ledger'").fetchone()
    if schema and "delta > 0" in schema[0]:
        connection.execute("ALTER TABLE points_ledger RENAME TO points_ledger_legacy")
        connection.execute("""CREATE TABLE points_ledger (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL REFERENCES points_wallets(user_id),
            kind TEXT NOT NULL, reference TEXT NOT NULL,
            delta INTEGER NOT NULL CHECK(delta != 0), balance_after INTEGER NOT NULL,
            created_at REAL NOT NULL, UNIQUE(kind, reference)
        )""")
        connection.execute("INSERT INTO points_ledger SELECT * FROM points_ledger_legacy")
        connection.execute("DROP TABLE points_ledger_legacy")
    else:
        connection.execute("""CREATE TABLE IF NOT EXISTS points_ledger (
            id INTEGER PRIMARY KEY, user_id TEXT NOT NULL REFERENCES points_wallets(user_id),
            kind TEXT NOT NULL, reference TEXT NOT NULL,
            delta INTEGER NOT NULL CHECK(delta != 0), balance_after INTEGER NOT NULL,
            created_at REAL NOT NULL, UNIQUE(kind, reference)
        )""")
    connection.execute("CREATE INDEX IF NOT EXISTS ledger_user ON points_ledger(user_id,id)")


def parse_points(value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 0 <= value <= 100_000_000:
        raise ValueError("积分须为 0–100000000 的整数")
    return value


def wallet_view(connection: sqlite3.Connection, user_id: str) -> dict[str, int]:
    row = connection.execute("SELECT balance FROM points_wallets WHERE user_id=?", (user_id,)).fetchone()
    return {"balance": row[0] if row else 0}


def credit_checkin(connection: sqlite3.Connection, user: dict, amount: int, reference: str, now: float) -> None:
    """Caller holds BEGIN IMMEDIATE; wallet, ledger and claim commit together."""
    if not connection.in_transaction:
        raise RuntimeError("积分入账必须处于写事务内")
    if type(amount) is not int or amount <= 0:
        raise ValueError("入账积分必须是正整数")
    existing = connection.execute("SELECT user_id,delta FROM points_ledger WHERE kind='checkin' AND reference=?", (reference,)).fetchone()
    if existing:
        if existing["user_id"] != user["id"] or existing["delta"] != amount:
            raise RuntimeError("积分流水与打卡记录不一致")
        return
    connection.execute("INSERT INTO points_wallets(user_id,username) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username", (user["id"], user["username"]))
    changed = connection.execute("UPDATE points_wallets SET balance=balance+? WHERE user_id=? AND balance<=?", (amount, user["id"], MAX_POINTS - amount)).rowcount
    if not changed:
        raise ValueError("积分余额超出上限")
    balance = wallet_view(connection, user["id"])["balance"]
    connection.execute("INSERT INTO points_ledger(user_id,kind,reference,delta,balance_after,created_at) VALUES (?,'checkin',?,?,?,?)", (user["id"], reference, amount, balance, now))


def spend_points(connection: sqlite3.Connection, user: dict, amount: int, kind: str, reference: str, now: float) -> int:
    """Caller holds BEGIN IMMEDIATE; deducts points from wallet and appends ledger record."""
    if not connection.in_transaction:
        raise RuntimeError("积分扣减必须处于写事务内")
    if type(amount) is not int or amount <= 0:
        raise ValueError("扣减积分必须是正整数")
    existing = connection.execute("SELECT user_id,delta FROM points_ledger WHERE kind=? AND reference=?", (kind, reference)).fetchone()
    if existing:
        return wallet_view(connection, user["id"])["balance"]
    current_balance = wallet_view(connection, user["id"])["balance"]
    if current_balance < amount:
        raise ValueError("站内积分余额不足")
    changed = connection.execute("UPDATE points_wallets SET balance=balance-? WHERE user_id=? AND balance>=?", (amount, user["id"], amount)).rowcount
    if not changed:
        raise ValueError("站内积分余额不足")
    balance = wallet_view(connection, user["id"])["balance"]
    connection.execute("INSERT INTO points_ledger(user_id,kind,reference,delta,balance_after,created_at) VALUES (?,?,?,?,?,?)", (user["id"], kind, reference, -amount, balance, now))
    return balance


def refund_points(connection: sqlite3.Connection, user: dict, amount: int, kind: str, reference: str, now: float) -> int:
    """Caller holds BEGIN IMMEDIATE; refunds points back to wallet on delivery failure."""
    if not connection.in_transaction:
        raise RuntimeError("积分退还必须处于写事务内")
    if type(amount) is not int or amount <= 0:
        raise ValueError("退还积分必须是正整数")
    existing = connection.execute("SELECT user_id,delta FROM points_ledger WHERE kind=? AND reference=?", (kind, reference)).fetchone()
    if existing:
        return wallet_view(connection, user["id"])["balance"]
    connection.execute("UPDATE points_wallets SET balance=balance+? WHERE user_id=?", (amount, user["id"]))
    balance = wallet_view(connection, user["id"])["balance"]
    connection.execute("INSERT INTO points_ledger(user_id,kind,reference,delta,balance_after,created_at) VALUES (?,?,?,?,?,?)", (user["id"], kind, reference, amount, balance, now))
    return balance


def ledger_view(connection: sqlite3.Connection, user_id: str, tz) -> list[dict]:
    rows = connection.execute("SELECT id,kind,reference,delta,balance_after,created_at FROM points_ledger WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,))
    result = []
    for row in rows:
        item = dict(row)
        item["created_at"] = datetime.fromtimestamp(row["created_at"], tz).isoformat(timespec="seconds")
        result.append(item)
    return result
