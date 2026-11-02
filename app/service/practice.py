from __future__ import annotations

import hmac
import math
import re
import secrets

from app.infrastructure.database import execute, fetch, fetch_one
from app.infrastructure.database.schemas import PracticeSession, PracticeTrigger, TrainingRecord
from app.utils.exceptions import APIError

IDLE_SECONDS = 600

_ROUND_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,128}")
_TRAINING_FIELDS = ("round_id", "started_at", "ended_at", "repetitions", "interval_seconds", "mode")

# 写函数（start/advance/complete/save_training_record）要求调用方已开启 database.write_txn()。


# ── 独立训练 ──────────────────────────────────────────────────────────────────

def training_record_view(row: dict) -> dict:
    return {field: row[field] for field in _TRAINING_FIELDS}


async def _training_leaderboard(day: str | None) -> list[dict]:
    day_filter = "AND t.day=$1" if day is not None else ""
    return await fetch(f"""
        WITH totals AS (
            SELECT t.user_id,MAX(t.username) AS username,SUM(t.repetitions) AS count,
                   MIN(t.received_at) AS first_received
            FROM training_records t
            LEFT JOIN reviews r ON r.day=t.day AND r.user_id=t.user_id
            WHERE (r.user_id IS NULL OR r.approved=1) {day_filter}
            GROUP BY t.user_id
        )
        SELECT ROW_NUMBER() OVER (ORDER BY count DESC,first_received,user_id) AS rank,
               username,count
        FROM totals ORDER BY rank LIMIT 50
    """, *((day,) if day is not None else ()))


async def training_data(user: dict | None, day: str) -> dict:
    records = [] if user is None else [
        training_record_view(row) for row in await fetch(
            "SELECT * FROM training_records WHERE user_id=$1 ORDER BY received_at DESC,id DESC LIMIT 50", user["id"])
    ]
    return {"leaderboard": await _training_leaderboard(day),
            "total_leaderboard": await _training_leaderboard(None), "records": records}


def _training_payload(body: dict) -> dict:
    round_id = body.get("round_id")
    if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.fullmatch(round_id):
        raise APIError("训练轮次编号格式错误", 400)
    values = {field: body.get(field) for field in ("started_at", "ended_at", "repetitions", "interval_seconds")}
    if type(values["started_at"]) is not int or type(values["ended_at"]) is not int:
        raise APIError("训练起止时间须为 Unix 毫秒整数", 400)
    if type(values["repetitions"]) is not int or not 1 <= values["repetitions"] <= 20:
        raise APIError("训练次数须为 1–20 的整数", 400)
    if type(values["interval_seconds"]) is not int or not 2 <= values["interval_seconds"] <= 10:
        raise APIError("每次训练时长须为 2–10 的整数秒", 400)
    mode = body.get("mode")
    if not isinstance(mode, str) or mode not in {"manual", "auto"}:
        raise APIError("训练模式须为 manual 或 auto", 400)
    if values["started_at"] >= values["ended_at"]:
        raise APIError("训练结束时间须晚于开始时间", 400)
    if values["ended_at"] - values["started_at"] < values["repetitions"] * values["interval_seconds"] * 1000:
        raise APIError("训练时长未达到次数与间隔要求", 400)
    return {"round_id": round_id, **values, "mode": mode}


async def save_training_record(user: dict, day: str, body: dict, now_ms: int) -> dict:
    payload = _training_payload(body)
    existing = await fetch_one("SELECT * FROM training_records WHERE user_id=$1 AND round_id=$2",
                               user["id"], payload["round_id"])
    if existing:
        if all(existing[field] == payload[field] for field in _TRAINING_FIELDS):
            return existing
        raise APIError("训练轮次编号已用于不同记录", 409)
    if payload["started_at"] < now_ms - 3_600_000:
        raise APIError("训练开始时间已超过一小时", 400)
    if payload["ended_at"] < now_ms - 300_000:
        raise APIError("训练结束时间已超过五分钟", 400)
    if payload["started_at"] > now_ms + 30_000 or payload["ended_at"] > now_ms + 30_000:
        raise APIError("训练时间不可超过服务器时间三十秒", 400)
    overlap = await fetch_one("SELECT 1 FROM training_records WHERE user_id=$1 AND started_at<$2 AND ended_at>$3 LIMIT 1",
                              user["id"], payload["ended_at"], payload["started_at"])
    if overlap:
        raise APIError("训练时间与已有记录重叠", 409)
    await TrainingRecord.create(user_id=user["id"], username=user["username"], day=day, round_id=payload["round_id"],
                                started_at=payload["started_at"], ended_at=payload["ended_at"],
                                repetitions=payload["repetitions"], interval_seconds=payload["interval_seconds"],
                                mode=payload["mode"], received_at=now_ms)
    return await fetch_one("SELECT * FROM training_records WHERE user_id=$1 AND round_id=$2",
                           user["id"], payload["round_id"])


# ── 首页打卡的逐次计时 ────────────────────────────────────────────────────────

async def get_session(day: str, user_id: str) -> dict | None:
    return await fetch_one("SELECT * FROM sessions WHERE day=$1 AND user_id=$2", day, user_id)


def view(row: dict | None, now: float) -> dict | None:
    if row is None or not row["flow_id"] or (row["step"] < row["repetitions"] and row["expires_at"] <= now):
        return None
    completed = row["step"] == row["repetitions"]
    result = {
        "token": row["token"], "mode": row["mode"], "repetitions": row["repetitions"],
        "step": row["step"], "completed": completed, "eligible": bool(row["eligible"]),
        "wait_seconds": max(0, math.ceil(row["updated_at"] + row["min_seconds"] - now)) if not completed else 0,
        "expires_in": max(0, math.ceil(row["expires_at"] - now)) if not completed else None,
    }
    if row["mode"] == "auto":
        result["interval_seconds"] = row["interval_seconds"]
    else:
        result["min_seconds"] = row["min_seconds"]
    return result


async def _add_trigger(row: dict, username: str, now: float) -> None:
    await PracticeTrigger.create(day=row["day"], user_id=row["user_id"], username=username, flow_id=row["flow_id"],
                                 group_no=row["step"] + 1, min_seconds=row["min_seconds"], created_at=now,
                                 mode=row["mode"], repetitions=row["repetitions"])


async def start(user: dict, day: str, eligible: bool, mode: str, repetitions: int,
                duration_seconds: int, now: float) -> dict:
    row = await get_session(day, user["id"])
    active = view(row, now)
    eligibility_upgrade = bool(row and eligible and not row["eligible"])
    repeat_completed = bool(row and row["step"] == row["repetitions"])
    same_settings = bool(row and row["mode"] == mode and row["repetitions"] == repetitions)
    if active and same_settings and not eligibility_upgrade and not repeat_completed:
        return row
    await execute("""INSERT INTO sessions(
            day,user_id,token,updated_at,expires_at,min_seconds,flow_id,eligible,mode,repetitions,interval_seconds)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(day,user_id) DO UPDATE SET
        token=excluded.token,step=0,updated_at=excluded.updated_at,expires_at=excluded.expires_at,
        min_seconds=excluded.min_seconds,flow_id=excluded.flow_id,eligible=excluded.eligible,
        mode=excluded.mode,repetitions=excluded.repetitions,interval_seconds=excluded.interval_seconds""",
        day, user["id"], secrets.token_urlsafe(32), now, now + IDLE_SECONDS, duration_seconds,
        secrets.token_hex(16), int(eligible), mode, repetitions, duration_seconds if mode == "auto" else None)
    row = await get_session(day, user["id"])
    await _add_trigger(row, user["username"], now)
    return row


async def _current(subject: str, day: str, token: str, now: float) -> dict:
    row = await get_session(day, subject)
    if not row or not view(row, now):
        raise APIError("超过十分钟未进入下一次，本轮已失效，请从第一次重新开始", 409)
    if not hmac.compare_digest(row["token"], token):
        raise APIError("练习凭证已使用，请刷新恢复进度", 409)
    return row


async def advance(user: dict, day: str, token: str, now: float) -> dict:
    row = await _current(user["id"], day, token, now)
    if row["step"] >= row["repetitions"] - 1:
        raise APIError(f"{row['repetitions']} 次练习均已触发，请等待最后一次计时结束", 409)
    remaining = row["updated_at"] + row["min_seconds"] - now
    if remaining > 0:
        raise APIError(f"本次间隔未达标，还需 {math.ceil(remaining)} 秒", 429)
    await execute("UPDATE sessions SET step=step+1,token=$1,updated_at=$2,expires_at=$3 WHERE day=$4 AND user_id=$5",
                  secrets.token_urlsafe(32), now, now + IDLE_SECONDS, day, user["id"])
    row = await get_session(day, user["id"])
    await _add_trigger(row, user["username"], now)
    return row


async def verify(flow_id: str | None, subject: str, day: str, finished_at: float) -> None:
    rows = await fetch("SELECT * FROM practice_triggers WHERE flow_id=$1 ORDER BY group_no", flow_id)
    repetitions = rows[0]["repetitions"] if rows else 0
    if repetitions < 1 or len(rows) != repetitions or [row["group_no"] for row in rows] != list(range(1, repetitions + 1)):
        raise APIError("缺少完整的练习触发记录，请从第一次重新练习", 409)
    minimum = rows[0]["min_seconds"]
    if minimum < 1 or any(row["user_id"] != subject or row["day"] != day or
                          row["min_seconds"] != minimum or row["repetitions"] != repetitions for row in rows):
        raise APIError("练习记录与账号不匹配，请重新练习", 409)
    timestamps = [row["created_at"] for row in rows]
    intervals = [timestamps[index] - timestamps[index - 1] for index in range(1, repetitions)]
    intervals.append(finished_at - timestamps[-1])
    if any(interval < minimum for interval in intervals):
        raise APIError("练习间隔尚未达标，请完成本次倒计时", 429)
    if any(interval >= IDLE_SECONDS for interval in intervals):
        raise APIError("超过十分钟未进入下一次，本轮练习已失效", 409)


async def complete(subject: str, day: str, token: str, now: float) -> dict:
    row = await _current(subject, day, token, now)
    if row["step"] == row["repetitions"]:
        return row
    if row["step"] < row["repetitions"] - 1:
        raise APIError(f"请逐次点击触发 {row['repetitions']} 次练习", 409)
    await verify(row["flow_id"], subject, day, now)
    await execute("UPDATE sessions SET step=repetitions,updated_at=$1 WHERE day=$2 AND user_id=$3", now, day, subject)
    return await get_session(day, subject)
