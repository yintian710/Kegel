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
    if "flow_id" not in columns:
        connection.execute("ALTER TABLE sessions ADD COLUMN flow_id TEXT NOT NULL DEFAULT ''")
        connection.execute("ALTER TABLE sessions ADD COLUMN eligible INTEGER NOT NULL DEFAULT 0")
        connection.execute("DELETE FROM sessions")
    entry_columns = {row["name"] for row in connection.execute("PRAGMA table_info(entries)")}
    if "flow_id" not in entry_columns:
        connection.execute("ALTER TABLE entries ADD COLUMN flow_id TEXT")
    connection.execute("""CREATE TABLE IF NOT EXISTS practice_triggers (
        id INTEGER PRIMARY KEY, day TEXT NOT NULL, user_id TEXT NOT NULL,
        username TEXT NOT NULL, flow_id TEXT NOT NULL, group_no INTEGER NOT NULL,
        min_seconds INTEGER NOT NULL, created_at REAL NOT NULL,
        UNIQUE(flow_id,group_no)
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS practice_day ON practice_triggers(day,id)")


def view(row, now: float) -> dict | None:
    if row is None or not row["flow_id"] or (row["step"] < 3 and row["expires_at"] <= now):
        return None
    return {"token": row["token"], "step": row["step"], "eligible": bool(row["eligible"]),
            "wait_seconds": max(0, math.ceil(row["updated_at"] + row["min_seconds"] - now)) if row["step"] < 3 else 0,
            "expires_in": max(0, math.ceil(row["expires_at"] - now)) if row["step"] < 3 else None}


def add_trigger(connection, row, username: str, now: float) -> None:
    connection.execute("INSERT INTO practice_triggers(day,user_id,username,flow_id,group_no,min_seconds,created_at) VALUES (?,?,?,?,?,?,?)",
                       (row["day"], row["user_id"], username, row["flow_id"], row["step"] + 1, row["min_seconds"], now))


def start(connection, user: dict, day: str, eligible: bool, min_seconds: int, now: float):
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, user["id"])).fetchone()
    if view(row, now) and not (eligible and not row["eligible"]):
        return row
    connection.execute("""INSERT INTO sessions(day,user_id,token,updated_at,expires_at,min_seconds,flow_id,eligible)
        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(day,user_id) DO UPDATE SET
        token=excluded.token,step=0,updated_at=excluded.updated_at,expires_at=excluded.expires_at,
        min_seconds=excluded.min_seconds,flow_id=excluded.flow_id,eligible=excluded.eligible""",
        (day, user["id"], secrets.token_urlsafe(32), now, now + IDLE_SECONDS, min_seconds, secrets.token_hex(16), int(eligible)))
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, user["id"])).fetchone()
    add_trigger(connection, row, user["username"], now)
    return row


def current(connection, subject: str, day: str, token: str, now: float):
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, subject)).fetchone()
    if not row or not view(row, now):
        raise PracticeError("超过十分钟未进入下一组，本轮已失效，请从第一组重新开始")
    if not hmac.compare_digest(row["token"], token):
        raise PracticeError("练习凭证已使用，请刷新恢复进度")
    return row


def advance(connection, user: dict, day: str, token: str, now: float):
    row = current(connection, user["id"], day, token, now)
    if row["step"] >= 2:
        raise PracticeError("三组练习均已触发，请等待最后一组计时结束")
    remaining = row["updated_at"] + row["min_seconds"] - now
    if remaining > 0:
        raise PracticeError(f"本组间隔未达标，还需 {math.ceil(remaining)} 秒", 429)
    connection.execute("UPDATE sessions SET step=step+1,token=?,updated_at=?,expires_at=? WHERE day=? AND user_id=?",
                       (secrets.token_urlsafe(32), now, now + IDLE_SECONDS, day, user["id"]))
    row = connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, user["id"])).fetchone()
    add_trigger(connection, row, user["username"], now)
    return row


def verify(connection, flow_id: str | None, subject: str, day: str, finished_at: float) -> None:
    rows = connection.execute("SELECT * FROM practice_triggers WHERE flow_id=? ORDER BY group_no", (flow_id,)).fetchall()
    if len(rows) != 3 or [row["group_no"] for row in rows] != [1, 2, 3]:
        raise PracticeError("缺少完整的三组触发记录，请从第一组重新练习")
    minimum = rows[0]["min_seconds"]
    if minimum < 1 or any(row["user_id"] != subject or row["day"] != day or row["min_seconds"] != minimum for row in rows):
        raise PracticeError("练习记录与账号不匹配，请重新练习")
    intervals = [rows[1]["created_at"] - rows[0]["created_at"], rows[2]["created_at"] - rows[1]["created_at"], finished_at - rows[2]["created_at"]]
    if any(interval < minimum for interval in intervals):
        raise PracticeError("练习间隔尚未达标，请完成本组倒计时", 429)
    if any(interval >= IDLE_SECONDS for interval in intervals):
        raise PracticeError("超过十分钟未进入下一组，本轮练习已失效")


def complete(connection, subject: str, day: str, token: str, now: float):
    row = current(connection, subject, day, token, now)
    if row["step"] < 2:
        raise PracticeError("请逐组点击触发三组练习")
    if row["step"] == 3:
        return row
    verify(connection, row["flow_id"], subject, day, now)
    connection.execute("UPDATE sessions SET step=3,token=? WHERE day=? AND user_id=?", (secrets.token_urlsafe(32), day, subject))
    return connection.execute("SELECT * FROM sessions WHERE day=? AND user_id=?", (day, subject)).fetchone()
