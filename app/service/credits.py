from __future__ import annotations

from typing import Any

from app.infrastructure.database import execute, fetch, fetch_one
from app.infrastructure.database.schemas import PointsLedger
from app.utils.timeutil import iso_time

MAX_POINTS = 9_000_000_000_000_000

# 本模块中所有写函数都要求调用方已开启 database.write_txn()：钱包、流水与业务凭证同事务提交。


def parse_points(value: Any) -> int:
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not 0 <= value <= 100_000_000:
        raise ValueError("积分须为 0–100000000 的整数")
    return value


async def balance_of(user_id: str) -> int:
    row = await fetch_one("SELECT balance FROM points_wallets WHERE user_id=$1", user_id)
    return row["balance"] if row else 0


async def wallet_view(user_id: str) -> dict[str, int]:
    return {"balance": await balance_of(user_id)}


async def _upsert_wallet(user: dict) -> None:
    await execute("INSERT INTO points_wallets(user_id,username) VALUES ($1,$2) "
                  "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username", user["id"], user["username"])


async def _append_ledger(user_id: str, kind: str, reference: str, delta: int, balance: int, now: float) -> None:
    await PointsLedger.create(user_id=user_id, kind=kind, reference=reference, delta=delta,
                              balance_after=balance, created_at=now)


async def _credit(user: dict, amount: int, kind: str, reference: str, now: float) -> None:
    await _upsert_wallet(user)
    changed = await execute("UPDATE points_wallets SET balance=balance+$1 WHERE user_id=$2 AND balance<=$3",
                            amount, user["id"], MAX_POINTS - amount)
    if not changed:
        raise ValueError("积分余额超出上限")
    await _append_ledger(user["id"], kind, reference, amount, await balance_of(user["id"]), now)


async def credit_checkin(user: dict, amount: int, reference: str, now: float) -> None:
    if type(amount) is not int or amount <= 0:
        raise ValueError("入账积分必须是正整数")
    existing = await fetch_one("SELECT user_id,delta FROM points_ledger WHERE kind='checkin' AND reference=$1", reference)
    if existing:
        if existing["user_id"] != user["id"] or existing["delta"] != amount:
            raise RuntimeError("积分流水与打卡记录不一致")
        return
    await _credit(user, amount, "checkin", reference, now)


async def spend_points(user: dict, amount: int, kind: str, reference: str, now: float) -> int:
    if type(amount) is not int or amount <= 0:
        raise ValueError("扣减积分必须是正整数")
    if await fetch_one("SELECT 1 FROM points_ledger WHERE kind=$1 AND reference=$2", kind, reference):
        return await balance_of(user["id"])
    if await balance_of(user["id"]) < amount:
        raise ValueError("站内积分余额不足")
    changed = await execute("UPDATE points_wallets SET balance=balance-$1 WHERE user_id=$2 AND balance>=$1",
                            amount, user["id"])
    if not changed:
        raise ValueError("站内积分余额不足")
    balance = await balance_of(user["id"])
    await _append_ledger(user["id"], kind, reference, -amount, balance, now)
    return balance


async def refund_points(user: dict, amount: int, kind: str, reference: str, now: float) -> int:
    if type(amount) is not int or amount <= 0:
        raise ValueError("退还积分必须是正整数")
    if await fetch_one("SELECT 1 FROM points_ledger WHERE kind=$1 AND reference=$2", kind, reference):
        return await balance_of(user["id"])
    await execute("UPDATE points_wallets SET balance=balance+$1 WHERE user_id=$2", amount, user["id"])
    balance = await balance_of(user["id"])
    await _append_ledger(user["id"], kind, reference, amount, balance, now)
    return balance


async def grant_points(user: dict, amount: Any, reference: str, now: float) -> dict:
    """An administrator request credits a wallet exactly once per reference."""
    amount = parse_points(amount)
    if amount <= 0:
        raise ValueError("增加积分必须是正整数")
    existing = await fetch_one("SELECT * FROM points_ledger WHERE kind='admin_credit' AND reference=$1", reference)
    if existing:
        if existing["user_id"] != user["id"] or existing["delta"] != amount:
            raise ValueError("此操作编号已用于其他加积分请求")
        return existing
    await _credit(user, amount, "admin_credit", reference, now)
    return await fetch_one("SELECT * FROM points_ledger WHERE kind='admin_credit' AND reference=$1", reference)


async def ledger_view(user_id: str) -> list[dict]:
    rows = await fetch("SELECT id,kind,reference,delta,balance_after,created_at FROM points_ledger "
                       "WHERE user_id=$1 ORDER BY id DESC LIMIT 100", user_id)
    return [{**row, "created_at": iso_time(row["created_at"])} for row in rows]
