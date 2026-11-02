from __future__ import annotations

import re

from app.config import Settings
from app.infrastructure.database import fetch, write_txn
from app.service import auth, catalog, checkin, credits, review
from app.utils import timeutil
from app.utils.exceptions import APIError

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")


async def overview(user: dict | None) -> dict:
    state = await checkin.status_view(user, timeutil.now())
    visits = await fetch("""
        SELECT v.subject AS user_id, MAX(v.username) AS username, COUNT(*) AS count,
               MAX(v.created_at) AS last_seen, COALESCE(r.reason,'') AS reason,
               COALESCE(r.approved,0) AS approved
        FROM visits v LEFT JOIN reviews r ON r.day=v.day AND r.user_id=v.subject
        WHERE v.day=$1 GROUP BY v.subject, r.reason, r.approved ORDER BY last_seen DESC LIMIT 200
    """, state["day"])
    for item in visits:
        item["last_seen"] = timeutil.iso_time(item["last_seen"])
    rewards = [checkin.entry_view(row) for row in await fetch("SELECT * FROM entries ORDER BY day DESC,rank LIMIT 500")]
    wallets = await fetch("SELECT user_id,username,balance FROM points_wallets ORDER BY balance DESC,user_id LIMIT 500")
    triggers = await fetch("SELECT day,user_id,username,group_no,created_at,flow_id FROM practice_triggers "
                           "ORDER BY id DESC LIMIT 200")
    for item in triggers:
        item["created_at"] = timeutil.iso_time(item["created_at"])
    return {"settings": await checkin.get_settings(), "status": state, "visits": visits, "rewards": rewards,
            "wallets": wallets, "practice_triggers": triggers,
            "products": await catalog.list_products(today=state["day"], include_inactive=True),
            "purchases": await catalog.all_purchases(),
            "admin_credit_enabled": bool(Settings.ADMIN_POINTS_PASSWORD_HASH)}


async def search_users(query: str) -> list[dict]:
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 128:
        raise APIError("请输入用户名或用户 ID（最多 128 字符）")
    query = query.strip().removeprefix("@")
    if not query:
        raise APIError("请输入用户名或用户 ID")
    return await fetch("""WITH known AS (
        SELECT user_id,username,1 AS priority,0::double precision AS seen_at FROM points_wallets
        UNION ALL SELECT subject,username,0,created_at FROM visits
        UNION ALL SELECT user_id,username,0,completed_at FROM entries
        UNION ALL SELECT user_id,username,0,created_at FROM donation_orders
    ), ranked AS (
        SELECT user_id,username,ROW_NUMBER() OVER (
            PARTITION BY user_id ORDER BY priority DESC,seen_at DESC,username
        ) AS pos FROM known
        WHERE user_id<>'' AND user_id !~ '[^0-9]'
    ) SELECT ranked.user_id,ranked.username,COALESCE(wallet.balance,0) AS balance
      FROM ranked LEFT JOIN points_wallets AS wallet USING(user_id)
      WHERE pos=1 AND (ranked.user_id=$1 OR strpos(lower(ranked.username),lower($1))>0)
      ORDER BY (ranked.user_id=$1) DESC,ranked.username,ranked.user_id LIMIT 50""", query)


async def approve_review(body: dict) -> None:
    if body.get("approved") is not True or not isinstance(body.get("user_id"), str):
        raise APIError("需指定审核账号并明确批准")
    await review.approve(body["user_id"], timeutil.day_key())


async def add_points(body: dict) -> dict:
    auth.verify_secondary_secret(body.get("secondary_secret"))
    user_id, request_id = body.get("user_id"), body.get("request_id")
    if not isinstance(user_id, str) or not user_id.isascii() or not user_id.isdecimal():
        raise APIError("请选择有效用户")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise APIError("加积分操作编号格式错误")
    try:
        amount = credits.parse_points(body.get("amount"))
    except ValueError as exc:
        raise APIError(str(exc)) from None
    if amount <= 0:
        raise APIError("增加积分必须是正整数")
    async with write_txn():
        found = next((item for item in await search_users(user_id) if item["user_id"] == user_id), None)
        if not found:
            raise APIError("没有找到此用户", 404)
        entry = await credits.grant_points({"id": user_id, "username": found["username"]},
                                           amount, request_id, timeutil.now())
        wallet = await credits.wallet_view(user_id)
    return {"user": {"id": user_id, "username": found["username"]}, "wallet": wallet, "entry": entry}
