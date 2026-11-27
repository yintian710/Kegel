from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.common.http_client import json_request
from app.config import Settings
from app.infrastructure.database import execute, fetch, fetch_one, write_txn
from app.service import auth, catalog, credits, practice, review, titles
from app.utils import timeutil
from app.utils.exceptions import APIError

DEFAULT_SETTINGS: dict[str, Any] = {
    "deadline": "22:00", "min_step_seconds": 8,
    "reward_tiers": [{"through": 10, "amount": 1000},
                     {"through": 20, "amount": 500},
                     {"through": 50, "amount": 100}],
    "condition_url": "",
    catalog.NO_PAYOUT_KEY: [],
    "ticket_reward_tiers": [],
}


# ── 配置 ──────────────────────────────────────────────────────────────────────

async def get_settings() -> dict[str, Any]:
    values = dict(DEFAULT_SETTINGS)
    values.update({row["key"]: json.loads(row["value"]) for row in await fetch("SELECT key,value FROM checkin_settings")})
    return values


def validate_settings(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) - set(DEFAULT_SETTINGS) - {"secondary_secret", "secondary_password"}:
        raise APIError("包含不支持的配置项")
    result: dict[str, Any] = {}
    if "deadline" in body:
        value = body["deadline"]
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except (ValueError, TypeError):
            raise APIError("最晚开启时间需为 HH:MM") from None
        if parsed.strftime("%H:%M") != value:
            raise APIError("最晚开启时间需为 HH:MM")
        result["deadline"] = value
    if "min_step_seconds" in body:
        value = body["min_step_seconds"]
        if type(value) is not int or not 1 <= value <= 300:
            raise APIError("每组最短时长需为 1–300 秒整数")
        result["min_step_seconds"] = value
    if "reward_tiers" in body:
        tiers = body["reward_tiers"]
        if not isinstance(tiers, list) or not 1 <= len(tiers) <= 20:
            raise APIError("奖励需配置 1–20 个连续档位")
        previous = 0
        normalized = []
        for tier in tiers:
            if not isinstance(tier, dict):
                raise APIError("奖励档位格式错误")
            through = tier.get("through")
            try:
                amount = credits.parse_points(tier.get("amount"))
            except ValueError as exc:
                raise APIError(str(exc)) from None
            if type(through) is not int or not previous < through <= 100000:
                raise APIError("档位截止名次须为递增的整数")
            normalized.append({"through": through, "amount": amount})
            previous = through
        result["reward_tiers"] = normalized
    if "ticket_reward_tiers" in body:
        tiers = body["ticket_reward_tiers"]
        if not isinstance(tiers, list) or len(tiers) > 20:
            raise APIError("送券档位需为至多 20 条的列表")
        normalized = []
        for tier in tiers:
            if not isinstance(tier, dict):
                raise APIError("送券档位格式错误")
            through = tier.get("through")
            ttype = tier.get("ticket_type")
            count = tier.get("count")
            if type(through) is not int or not 1 <= through <= 100000:
                raise APIError("送券档位截止名次须为 1–100000 的整数")
            if ttype not in titles.TICKET_TYPES:
                raise APIError("送券档位的券类型须为 single / ten / hundred")
            if type(count) is not int or not 1 <= count <= 1000:
                raise APIError("送券数量须为 1–1000 的整数")
            normalized.append({"through": through, "ticket_type": ttype, "count": count})
        normalized.sort(key=lambda item: item["through"])
        result["ticket_reward_tiers"] = normalized
    if "condition_url" in body:
        value = body["condition_url"]
        if not isinstance(value, str) or len(value) > 2048:
            raise APIError("条件 API 地址格式错误")
        parsed_url = urlsplit(value)
        if value and (parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname
                      or parsed_url.username or parsed_url.password):
            raise APIError("条件 API 必须是 HTTP(S) 地址，认证密钥请配置环境变量")
        result["condition_url"] = value
    if catalog.NO_PAYOUT_KEY in body:
        ids = body[catalog.NO_PAYOUT_KEY]
        if not isinstance(ids, list) or len(ids) > 200 or not all(
                isinstance(item, str) and item.isascii() and item.isdecimal() and len(item) <= 20 for item in ids):
            raise APIError("不发货名单须为至多 200 个纯数字 LINUX DO 用户 ID")
        result[catalog.NO_PAYOUT_KEY] = list(dict.fromkeys(ids))
    return result


async def save_settings(body: dict[str, Any]) -> None:
    values = validate_settings(body)
    async with write_txn():
        for key, value in values.items():
            await execute("INSERT INTO checkin_settings(key,value) VALUES ($1,$2) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", key, json.dumps(value))


# ── 开放日 ────────────────────────────────────────────────────────────────────

async def ensure_day(now: float) -> dict:
    today = timeutil.day_key(now)
    await execute("INSERT INTO days(day) VALUES ($1) ON CONFLICT(day) DO NOTHING", today)
    if timeutil.clock_hhmm(now) >= (await get_settings())["deadline"]:
        await execute("UPDATE days SET opened_at=$1,open_reason='deadline' WHERE day=$2 AND opened_at IS NULL", now, today)
    return await fetch_one("SELECT * FROM days WHERE day=$1", today)


async def open_today(reason: str) -> None:
    async with write_txn():
        now = timeutil.now()
        today = (await ensure_day(now))["day"]
        await execute("UPDATE days SET opened_at=$1,open_reason=$2 WHERE day=$3 AND opened_at IS NULL", now, reason, today)



def _previous_workday(value: date) -> date:
    value -= timedelta(days=1)
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


async def _workday_streak(user_id: str, day: str) -> int:
    current = date.fromisoformat(day)
    completed: set[date] = set()
    for row in await fetch("SELECT day FROM entries WHERE user_id=$1 AND day<$2 ORDER BY day DESC", user_id, day):
        completed_day = date.fromisoformat(row["day"])
        if completed_day.weekday() < 5:
            completed.add(completed_day)

    streak = 1 if current.weekday() < 5 else 0
    expected = _previous_workday(current)
    while expected in completed:
        streak += 1
        expected = _previous_workday(expected)
    return streak


def _streak_ending(workdays: set[date], last: date) -> int:
    """以 last（已完成的工作日）为末日向前数连续工作日；周末不增天也不中断（同 _workday_streak）。"""
    streak, expected = 1, _previous_workday(last)
    while expected in workdays:
        streak += 1
        expected = _previous_workday(expected)
    return streak


async def streak_leaderboard(today: str, limit: int = 50) -> dict:
    """连续打卡榜：按当前连续工作日数排名。今日已完成，或上一个工作日已完成（连续仍有效）的用户才上榜。
    不发货名单用户置灰、不占名次（与每日榜一致）。"""
    current = date.fromisoformat(today)
    previous = _previous_workday(current)
    days_by_user: dict[str, set[date]] = {}
    names: dict[str, str] = {}
    for row in await fetch("SELECT user_id,username,day FROM entries WHERE day>=$1 ORDER BY day",
                           (current - timedelta(days=400)).isoformat()):
        days_by_user.setdefault(row["user_id"], set()).add(date.fromisoformat(row["day"]))
        names[row["user_id"]] = row["username"]
    skipped = await catalog.no_payout_ids()
    rows = []
    for user_id, days in days_by_user.items():
        workdays = {d for d in days if d.weekday() < 5}
        done_today = current in workdays
        if done_today:
            streak = _streak_ending(workdays, current)
        elif previous in workdays:
            streak = _streak_ending(workdays, previous)
        else:
            continue
        rows.append({"user_id": user_id, "username": names[user_id], "streak_days": streak, "done_today": done_today})
    rows.sort(key=lambda r: (-r["streak_days"], not r["done_today"], r["username"].lower()))
    items, counted = [], 0
    for position, row in enumerate(rows[:limit], start=1):
        is_skipped = row["user_id"] in skipped
        if not is_skipped:
            counted += 1
        items.append({"rank": None if is_skipped else counted, "position": position, "skipped": is_skipped,
                      "username": row["username"], "streak_days": row["streak_days"], "done_today": row["done_today"]})
    return {"day": today, "items": items}


def _streak_bonus_percent(streak_days: int) -> int:
    return min(max(streak_days - 1, 0), 100)


def _apply_streak_bonus(amount: int, bonus_percent: int) -> int:
    return amount * (100 + bonus_percent) // 100

# ── 视图 ──────────────────────────────────────────────────────────────────────

def entry_view(row: dict | None, streak_days: int | None = None) -> dict | None:
    if row is None:
        return None
    result = {**row, "completed_at": timeutil.iso_time(row["completed_at"]),
              "claimed_at": timeutil.iso_time(row["claimed_at"])}
    if streak_days is not None:
        result.update(streak_days=streak_days, reward_bonus_percent=_streak_bonus_percent(streak_days))
    return result


async def _entry(day: str, user_id: str) -> dict | None:
    return await fetch_one("SELECT * FROM entries WHERE day=$1 AND user_id=$2", day, user_id)


async def _effective_ranks(day: str) -> dict[str, int | None]:
    """当日名次（不发货名单用户不占名次，None）。entries.rank 仍是按完成先后的唯一序号。"""
    skipped = await catalog.no_payout_ids()
    ranks: dict[str, int | None] = {}
    counted = 0
    for row in await fetch("SELECT user_id FROM entries WHERE day=$1 ORDER BY rank", day):
        if row["user_id"] in skipped:
            ranks[row["user_id"]] = None
        else:
            counted += 1
            ranks[row["user_id"]] = counted
    return ranks


def _ranked(view: dict | None, ranks: dict[str, int | None]) -> dict | None:
    """名单用户保留原序号并标记 skipped；其余用户 rank 替换为不含名单用户的名次。"""
    if view is None:
        return None
    effective = ranks.get(view["user_id"])
    return {**view, "rank": view["rank"] if effective is None else effective, "skipped": effective is None}


async def status_view(user: dict | None, now: float, subject: str = "") -> dict:
    day = await ensure_day(now)
    config = await get_settings()
    identity = user["id"] if user else subject
    entry = await _entry(day["day"], identity)
    if entry and entry["reward_status"] == "unclaimed" and not entry["flow_id"]:
        entry = None
    session = await practice.get_session(day["day"], identity)
    pending = await review.has_pending_review(day["day"], identity)
    if session and not session["eligible"] and user and day["opened_at"] is not None and not pending:
        session = None
    streak_days = await _workday_streak(identity, day["day"]) if user else 0
    ranks = await _effective_ranks(day["day"])
    board = [{"rank": ranks.get(row["user_id"]), "position": row["rank"], "skipped": ranks.get(row["user_id"]) is None,
              "username": row["username"], "amount": row["amount"], "reward_status": row["reward_status"],
              "completed_at": timeutil.iso_time(row["completed_at"])}
             for row in await fetch("SELECT rank,user_id,username,amount,reward_status,completed_at FROM entries "
                                    "WHERE day=$1 ORDER BY rank LIMIT 50", day["day"])]
    return {"user": user, "day": day["day"], "is_open": day["opened_at"] is not None,
            "opened_at": timeutil.iso_time(day["opened_at"]), "open_reason": day["open_reason"],
            "deadline": config["deadline"], "timezone": Settings.SITE_TZ_NAME,
            "min_step_seconds": config["min_step_seconds"], "reward_tiers": config["reward_tiers"],
            "wallet": await credits.wallet_view(identity) if user else None,
            "quota": await catalog.quota_view(day["day"]), "oauth_ready": Settings.oauth_ready(),
            "total": (await fetch_one("SELECT COUNT(*) AS n FROM entries WHERE day=$1", day["day"]))["n"],
            "entry": _ranked(entry_view(entry, streak_days if entry else None), ranks),
            "session": practice.view(session, now), "review": pending,
            "streak_days": streak_days, "leaderboard": board}


async def practice_api_view(user: dict | None, today: str) -> dict:
    result = {"user": user, "oauth_ready": Settings.oauth_ready(), "day": today}
    result.update(await practice.training_data(user, today))
    return result


# ── 访问记录 ──────────────────────────────────────────────────────────────────

async def record_visit_for(user: dict | None, visitor: str, ip: str, kind: str, now: float) -> None:
    subject = user["id"] if user else f"anon:{visitor}"
    async with write_txn():
        await review.record_visit(subject, user["username"] if user else "匿名访客", visitor, ip, kind, now)


async def visit(user: dict | None, visitor: str, ip: str) -> dict:
    now = timeutil.now()
    await record_visit_for(user, visitor, ip, "visit", now)
    return await status_view(user, now, auth.practice_identity(user, visitor)["id"])


# ── 首页打卡流程 ──────────────────────────────────────────────────────────────

async def _record_attempt(user: dict | None, visitor: str, ip: str, skip_auto_step: bool = False) -> None:
    identity = user or {"id": f"anon:{visitor}"}
    if skip_auto_step:
        row = await practice.get_session(timeutil.day_key(), identity["id"])
        if row and row["mode"] == "auto":
            return
    await record_visit_for(user, visitor, ip, "trigger", timeutil.now())


async def start_session(user: dict | None, visitor: str, ip: str, body: dict) -> dict:
    await _record_attempt(user, visitor, ip)
    mode = body.get("mode", "manual")
    repetitions = body.get("repetitions", 3) if mode == "manual" else body.get("repetitions")
    if mode not in {"manual", "auto"}:
        raise APIError("练习模式仅支持 manual 或 auto")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 20:
        raise APIError("练习次数须为 1–20 的整数")
    identity = auth.practice_identity(user, visitor)
    async with write_txn():
        now = timeutil.now()
        day = await ensure_day(now)
        config = await get_settings()
        interval_seconds = body.get("interval_seconds") if mode == "auto" else config["min_step_seconds"]
        if mode == "auto" and (isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int)
                               or not 2 <= interval_seconds <= 5):
            raise APIError("自动练习间隔须为 2–5 秒的整数")
        pending = await review.has_pending_review(day["day"], identity["id"])
        eligible = bool(user and day["opened_at"] is not None and not pending)
        row = await practice.start(identity, day["day"], eligible, mode, repetitions, interval_seconds, now)
    return {"session": practice.view(row, now)}


async def advance_session(user: dict | None, visitor: str, ip: str, body: dict) -> dict:
    await _record_attempt(user, visitor, ip, skip_auto_step=True)
    token = body.get("token")
    if not isinstance(token, str):
        raise APIError("缺少练习凭证")
    identity = auth.practice_identity(user, visitor)
    async with write_txn():
        now = timeutil.now()
        row = await practice.advance(identity, timeutil.day_key(now), token, now)
    return {"session": practice.view(row, now)}


async def complete_session(user: dict | None, visitor: str, body: dict) -> dict:
    token = body.get("token")
    if not isinstance(token, str):
        raise APIError("缺少练习凭证")
    identity = auth.practice_identity(user, visitor)
    async with write_txn():
        now = timeutil.now()
        today = timeutil.day_key(now)
        row = await practice.complete(identity["id"], today, token, now)
        entry = None
        streak_days = None
        if user:
            pending = await review.has_pending_review(today, user["id"])
            if row["eligible"] and not pending:
                rank = (await fetch_one("SELECT COUNT(*)+1 AS n FROM entries WHERE day=$1", today))["n"]
                # 不发货名单用户不占名次：其他人按「不含名单用户」的名次领奖；名单用户自己的积分奖励按原序号计算、保持不变。
                skipped = await catalog.no_payout_ids()
                reward_rank = rank if user["id"] in skipped else (await fetch_one(
                    "SELECT COUNT(*)+1 AS n FROM entries WHERE day=$1 AND user_id <> ALL($2::text[])",
                    today, list(skipped)))["n"]
                base_amount = next((tier["amount"] for tier in (await get_settings())["reward_tiers"]
                                    if reward_rank <= tier["through"]), 0)
                streak_days = await _workday_streak(user["id"], today)
                amount = _apply_streak_bonus(base_amount, _streak_bonus_percent(streak_days))
                await execute("""INSERT INTO entries(day,user_id,username,rank,amount,completed_at,reward_status,flow_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(day,user_id) DO UPDATE SET
                    flow_id=excluded.flow_id,completed_at=excluded.completed_at
                    WHERE entries.reward_status='unclaimed' AND entries.flow_id IS NULL""",
                              today, user["id"], user["username"], rank, amount, row["updated_at"],
                              "unclaimed" if amount > 0 else "none", row["flow_id"])
            entry = await _entry(today, user["id"])
            ranks = await _effective_ranks(today)
            if entry and not pending:
                await titles.grant_checkin_tickets(user["id"], ranks.get(user["id"]) or int(entry["rank"]), today, now)
            if entry and streak_days is None:
                streak_days = await _workday_streak(user["id"], today)
        return {"session": practice.view(row, now), "entry": _ranked(entry_view(entry, streak_days), ranks) if entry else None}


async def claim(user: dict) -> dict:
    async with write_txn():
        now = timeutil.now()
        today = timeutil.day_key(now)
        await review.check_review(user["id"], today)
        row = await _entry(today, user["id"])
        if not row:
            raise APIError("请先完成打卡练习", 409)
        if row["reward_status"] == "unclaimed":
            await practice.verify(row["flow_id"], user["id"], today, row["completed_at"])
            await credits.credit_checkin(user, row["amount"], f"{today}:{user['id']}", now)
            await execute("UPDATE entries SET reward_status='credited',claimed_at=$1 WHERE day=$2 AND user_id=$3",
                          now, today, user["id"])
            row = await _entry(today, user["id"])
        streak_days = await _workday_streak(user["id"], today)
        return {"entry": entry_view(row, streak_days), "wallet": await credits.wallet_view(user["id"]),
                "quota": await catalog.quota_view(today)}


async def upload_training_record(user: dict, body: dict) -> dict:
    expected = body.get("expected_user_id")
    if expected is not None and expected != user["id"]:
        raise APIError("登录账号已切换，请刷新后重新训练", 409)
    now = timeutil.now()
    today = timeutil.day_key(now)
    async with write_txn():
        await review.check_review(user["id"], today)
        row = await practice.save_training_record(user, today, body, int(now * 1000))
    result = await practice_api_view(user, today)
    result["record"] = practice.training_record_view(row)
    return result


# ── 定时任务 ──────────────────────────────────────────────────────────────────

_next_condition = 0.0


async def tick() -> None:
    """Once a second: roll the day over and, while closed, poll the optional condition URL every 30 seconds."""
    global _next_condition
    try:
        day = await ensure_day(timeutil.now())
        url = (await get_settings())["condition_url"]
        monotonic = time.monotonic()
        if day["opened_at"] is None and url and monotonic >= _next_condition:
            _next_condition = monotonic + 30
            headers = {"Authorization": f"Bearer {Settings.CONDITION_TOKEN}"} if Settings.CONDITION_TOKEN else {}
            result = await json_request(url, headers=headers, timeout=5)
            # 只把响应应用到发起请求时的那一天。
            if result.get("open") is True and day["day"] == timeutil.day_key():
                await open_today("condition")
    except Exception as exc:
        print(f"开启条件检查失败: {type(exc).__name__}", flush=True)
