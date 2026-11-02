from __future__ import annotations

import hashlib
import hmac

from app.config import Settings
from app.infrastructure.database import execute, fetch, fetch_one
from app.infrastructure.database.schemas import Visit
from app.utils import timeutil
from app.utils.exceptions import APIError

# 访问记录只辅助识别规律性访问，写函数要求调用方已开启 database.write_txn()。


async def check_review(subject: str, today: str) -> None:
    row = await fetch_one("SELECT * FROM reviews WHERE day=$1 AND user_id=$2", today, subject)
    if row and not row["approved"]:
        raise APIError(f"访问规律异常，等待管理员审核：{row['reason']}", 403)


async def has_pending_review(day: str, subject: str) -> dict | None:
    return await fetch_one("SELECT reason,approved FROM reviews WHERE day=$1 AND user_id=$2 AND approved=0", day, subject)


async def record_visit(subject: str, username: str, visitor: str, ip: str, kind: str, now: float) -> None:
    today = timeutil.day_key(now)
    ip_hash = hmac.new(Settings.APP_SECRET, ip.encode(), hashlib.sha256).hexdigest()[:24]
    await Visit.create(day=today, subject=subject, username=username, visitor=visitor,
                       ip_hash=ip_hash, kind=kind, created_at=now)
    recent_count = (await fetch_one("SELECT COUNT(*) AS n FROM visits WHERE subject=$1 AND created_at>$2",
                                    subject, now - 600))["n"]
    rows = await fetch("SELECT created_at FROM visits WHERE subject=$1 AND kind=$2 ORDER BY id DESC LIMIT 6",
                       subject, kind)
    reason = ""
    if recent_count >= 20:
        reason = "10 分钟内访问或启动次数达到 20 次"
    elif len(rows) == 6:
        stamps = [row["created_at"] for row in rows]
        intervals = [stamps[i] - stamps[i + 1] for i in range(5)]
        mean = sum(intervals) / 5
        if 30 <= mean <= 172800 and max(intervals) - min(intervals) <= max(2, mean * .02):
            reason = "连续 6 次访问呈固定周期"
    if reason:
        await execute("INSERT INTO reviews(day,user_id,reason) VALUES ($1,$2,$3) "
                      "ON CONFLICT(day,user_id) DO UPDATE SET reason=excluded.reason", today, subject, reason)


async def approve(user_id: str, day: str) -> None:
    if not await execute("UPDATE reviews SET approved=1 WHERE day=$1 AND user_id=$2", day, user_id):
        raise APIError("没有找到待审核记录", 404)
