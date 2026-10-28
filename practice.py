from __future__ import annotations

import hmac
import math
import secrets
import sqlite3

IDLE_SECONDS = 600


class PracticeError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def init_schema(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
    additions = {
        "flow_id": "TEXT NOT NULL DEFAULT ''",
        "eligible": "INTEGER NOT NULL DEFAULT 0",
        "mode": "TEXT NOT NULL DEFAULT 'manual'",
        "repetitions": "INTEGER NOT NULL DEFAULT 3",
        "interval_seconds": "INTEGER",
    }
    reset_sessions = "flow_id" not in columns
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
    if reset_sessions:
        connection.execute("DELETE FROM sessions")

    entry_columns = {row["name"] for row in connection.execute("PRAGMA table_info(entries)")}
    if "flow_id" not in entry_columns:
        connection.execute("ALTER TABLE entries ADD COLUMN flow_id TEXT")

    connection.execute("""CREATE TABLE IF NOT EXISTS practice_triggers (
        id INTEGER PRIMARY KEY, day TEXT NOT NULL, user_id TEXT NOT NULL,
        username TEXT NOT NULL, flow_id TEXT NOT NULL, group_no INTEGER NOT NULL,
        min_seconds INTEGER NOT NULL, created_at REAL NOT NULL,
        mode TEXT NOT NULL DEFAULT 'manual', repetitions INTEGER NOT NULL DEFAULT 3,
        UNIQUE(flow_id,group_no)
    )""")
    trigger_columns = {row["name"] for row in connection.execute("PRAGMA table_info(practice_triggers)")}
    if "mode" not in trigger_columns:
        connection.execute("ALTER TABLE practice_triggers ADD COLUMN mode TEXT NOT NULL DEFAULT 'manual'")
    if "repetitions" not in trigger_columns:
        connection.execute("ALTER TABLE practice_triggers ADD COLUMN repetitions INTEGER NOT NULL DEFAULT 3")
    connection.execute("CREATE INDEX IF NOT EXISTS practice_day ON practice_triggers(day,id)")

    connection.execute("""CREATE TABLE IF NOT EXISTS practice_completions (
        id INTEGER PRIMARY KEY, day TEXT NOT NULL, user_id TEXT NOT NULL,
        username TEXT NOT NULL, flow_id TEXT NOT NULL UNIQUE,
        repetitions INTEGER NOT NULL CHECK(repetitions > 0), completed_at REAL NOT NULL
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS practice_completions_day ON practice_completions(day,user_id)")
    connection.execute("""INSERT OR IGNORE INTO practice_completions(
            day,user_id,username,flow_id,repetitions,completed_at)
        SELECT day,user_id,username,flow_id,3,completed_at FROM entries
        WHERE flow_id IS NOT NULL AND flow_id != ''""")


def view(row, now: float) -> dict | None:
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


def add_trigger(connection, row, username: str, now: float) -> None:
    connection.execute("""INSERT INTO practice_triggers(
            day,user_id,username,flow_id,group_no,min_seconds,created_at,mode,repetitions)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (row["day"], row["user_id"], username, row["flow_id"], row["step"] + 1,
         row["min_seconds"], now, row["mode"], row["repetitions"]))


def start(connection, user: dict, day: str, eligible: bool, mode: str, repetitions: int,
          duration_seconds: int, now: float):
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, user["id"])).fetchone()
    active = view(row, now)
    eligibility_upgrade = bool(row and eligible and not row["eligible"])
    repeat_completed = bool(row and row["step"] == row["repetitions"])
    same_settings = bool(row and row["mode"] == mode and row["repetitions"] == repetitions)
    if active and same_settings and not eligibility_upgrade and not repeat_completed:
        return row
    connection.execute("""INSERT INTO sessions(
            day,user_id,token,updated_at,expires_at,min_seconds,flow_id,eligible,mode,repetitions,interval_seconds)
        VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(day,user_id) DO UPDATE SET
        token=excluded.token,step=0,updated_at=excluded.updated_at,expires_at=excluded.expires_at,
        min_seconds=excluded.min_seconds,flow_id=excluded.flow_id,eligible=excluded.eligible,
        mode=excluded.mode,repetitions=excluded.repetitions,interval_seconds=excluded.interval_seconds""",
        (day, user["id"], secrets.token_urlsafe(32), now, now + IDLE_SECONDS, duration_seconds,
         secrets.token_hex(16), int(eligible), mode, repetitions,
         duration_seconds if mode == "auto" else None))
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, user["id"])).fetchone()
    add_trigger(connection, row, user["username"], now)
    return row


def current(connection, subject: str, day: str, token: str, now: float):
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, subject)).fetchone()
    if not row or not view(row, now):
        raise PracticeError("超过十分钟未进入下一次，本轮已失效，请从第一次重新开始")
    if not hmac.compare_digest(row["token"], token):
        raise PracticeError("练习凭证已使用，请刷新恢复进度")
    return row


def advance(connection, user: dict, day: str, token: str, now: float):
    row = current(connection, user["id"], day, token, now)
    if row["step"] >= row["repetitions"] - 1:
        raise PracticeError(f"{row['repetitions']} 次练习均已触发，请等待最后一次计时结束")
    remaining = row["updated_at"] + row["min_seconds"] - now
    if remaining > 0:
        raise PracticeError(f"本次间隔未达标，还需 {math.ceil(remaining)} 秒", 429)
    connection.execute("UPDATE sessions SET step=step+1,token=?,updated_at=?,expires_at=? WHERE day=? AND user_id=?",
                       (secrets.token_urlsafe(32), now, now + IDLE_SECONDS, day, user["id"]))
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, user["id"])).fetchone()
    add_trigger(connection, row, user["username"], now)
    return row


def verify(connection, flow_id: str | None, subject: str, day: str, finished_at: float) -> None:
    rows = connection.execute("SELECT * FROM practice_triggers WHERE flow_id=? ORDER BY group_no", (flow_id,)).fetchall()
    repetitions = rows[0]["repetitions"] if rows else 0
    if repetitions < 1 or len(rows) != repetitions or [row["group_no"] for row in rows] != list(range(1, repetitions + 1)):
        raise PracticeError("缺少完整的练习触发记录，请从第一次重新练习")
    minimum = rows[0]["min_seconds"]
    if minimum < 1 or any(row["user_id"] != subject or row["day"] != day or
                          row["min_seconds"] != minimum or row["repetitions"] != repetitions for row in rows):
        raise PracticeError("练习记录与账号不匹配，请重新练习")
    timestamps = [row["created_at"] for row in rows]
    intervals = [timestamps[index] - timestamps[index - 1] for index in range(1, repetitions)]
    intervals.append(finished_at - timestamps[-1])
    if any(interval < minimum for interval in intervals):
        raise PracticeError("练习间隔尚未达标，请完成本次倒计时", 429)
    if any(interval >= IDLE_SECONDS for interval in intervals):
        raise PracticeError("超过十分钟未进入下一次，本轮练习已失效")


def complete(connection, subject: str, day: str, token: str, now: float):
    row = current(connection, subject, day, token, now)
    if row["step"] == row["repetitions"]:
        return row
    if row["step"] < row["repetitions"] - 1:
        raise PracticeError(f"请逐次点击触发 {row['repetitions']} 次练习")
    verify(connection, row["flow_id"], subject, day, now)
    connection.execute("UPDATE sessions SET step=repetitions,updated_at=? WHERE day=? AND user_id=?", (now, day, subject))
    return connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, subject)).fetchone()
