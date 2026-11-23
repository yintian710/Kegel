from __future__ import annotations

import json
import re
import secrets
from typing import Any

from app.infrastructure.database import execute, fetch, fetch_one, write_txn
from app.service import credits
from app.utils import timeutil
from app.utils.exceptions import APIError
from app.utils.snowflake import next_id

# ── 常量 ──────────────────────────────────────────────────────────────────────
RARITIES = ("N", "R", "SR", "SSR", "UR")
TICKET_TYPES = ("single", "ten", "hundred")
TICKET_DRAWS = {"single": 1, "ten": 10, "hundred": 100}
TICKET_COL = {"single": "tickets_single", "ten": "tickets_ten", "hundred": "tickets_hundred"}
DRAW_TO_TICKET = {1: "single", 10: "ten", 100: "hundred"}
BASE_WEIGHT = {"N": 60, "R": 28, "SR": 9, "SSR": 3}
PITY_LIMIT = 80
SOFT_PITY_START = 70
NEXT_RARITY = {"N": "R", "R": "SR", "SR": "SSR"}
SMELT_COST = {"N": {"random": 3, "target": 6}, "R": {"random": 3, "target": 6},
              "SR": {"random": 5, "target": 10}}
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_CODE_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


# ── 基础状态 ──────────────────────────────────────────────────────────────────

async def _ensure_state(user_id: str) -> None:
    await execute("INSERT INTO user_title_state(user_id) VALUES ($1) ON CONFLICT(user_id) DO NOTHING", user_id)


async def _state(user_id: str) -> dict:
    row = await fetch_one("SELECT * FROM user_title_state WHERE user_id=$1", user_id)
    if not row:
        await _ensure_state(user_id)
        row = await fetch_one("SELECT * FROM user_title_state WHERE user_id=$1", user_id)
    return row


def _tickets_of(state: dict) -> dict[str, int]:
    return {t: int(state[TICKET_COL[t]]) for t in TICKET_TYPES}


async def _config(key: str, default: Any) -> Any:
    row = await fetch_one("SELECT value FROM title_config WHERE key=$1", key)
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return default


async def set_config(key: str, value: Any) -> None:
    await execute("INSERT INTO title_config(key,value) VALUES ($1,$2) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", key, json.dumps(value, ensure_ascii=False))


# ── 券流水（同一 user/券型/来源/引用 幂等）────────────────────────────────────

async def _ticket_apply(user_id: str, ticket_type: str, delta: int, reason: str, reference: str, now: float) -> bool:
    if ticket_type not in TICKET_COL:
        raise APIError("券类型不正确")
    existing = await fetch_one(
        "SELECT 1 FROM title_ticket_ledger WHERE user_id=$1 AND ticket_type=$2 AND reason=$3 AND reference=$4",
        user_id, ticket_type, reason, reference)
    if existing:
        return False
    await _ensure_state(user_id)
    col = TICKET_COL[ticket_type]
    changed = await execute(f"UPDATE user_title_state SET {col}={col}+$1 WHERE user_id=$2 AND {col}+$1>=0",
                            delta, user_id)
    if not changed:
        raise APIError("该券数量不足", 400)
    balance = (await _state(user_id))[col]
    await execute(
        "INSERT INTO title_ticket_ledger(id,user_id,ticket_type,delta,reason,reference,balance_after,created_at) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        next_id(), user_id, ticket_type, delta, reason, reference, balance, now)
    return True


async def grant_checkin_tickets(user_id: str, rank: int, day: str, now: float) -> None:
    """按 checkin_settings.ticket_reward_tiers 在打卡完成时发券，reference=checkin:{day} 幂等。"""
    row = await fetch_one("SELECT value FROM checkin_settings WHERE key='ticket_reward_tiers'")
    if not row:
        return
    try:
        tiers = json.loads(row["value"])
    except (ValueError, TypeError):
        return
    if not isinstance(tiers, list) or not tiers:
        return
    matched = [t for t in tiers if isinstance(t, dict) and type(t.get("through")) is int and rank <= t["through"]]
    if not matched:
        return
    min_through = min(t["through"] for t in matched)
    for tier in matched:
        if tier["through"] != min_through:
            continue
        ttype, count = tier.get("ticket_type"), tier.get("count")
        if ttype in TICKET_COL and type(count) is int and count > 0:
            await _ticket_apply(user_id, ttype, count, "checkin", f"checkin:{day}", now)


# ── 抽卡：随机与保底 ──────────────────────────────────────────────────────────

def _pick_weighted(rows: list[dict]) -> dict:
    total = sum(int(r["weight"]) for r in rows)
    roll = secrets.randbelow(total)
    acc = 0
    for row in rows:
        acc += int(row["weight"])
        if roll < acc:
            return row
    return rows[-1]


def _choose_rarity(pity: int, pools: dict[str, list[dict]]) -> str:
    has_ssr = bool(pools.get("SSR"))
    if has_ssr:
        chance = 30 + max(0, pity - SOFT_PITY_START) * 97  # 千分比；80 抽时 >=1000
        if chance >= 1000 or secrets.randbelow(1000) < chance:
            return "SSR"
    options = [(r, BASE_WEIGHT[r]) for r in ("N", "R", "SR") if pools.get(r)]
    total = sum(w for _, w in options)
    roll = secrets.randbelow(total)
    acc = 0
    for rarity, weight in options:
        acc += weight
        if roll < acc:
            return rarity
    return options[-1][0]


async def _load_pools() -> dict[str, list[dict]]:
    rows = await fetch("SELECT id,code,rarity,weight FROM title_defs WHERE is_active=1 "
                       "AND rarity IN ('N','R','SR','SSR')")
    pools: dict[str, list[dict]] = {}
    for row in rows:
        pools.setdefault(row["rarity"], []).append(row)
    return pools


async def _give_title(user_id: str, title_id: int, now: float) -> bool:
    row = await fetch_one("SELECT copies FROM user_titles WHERE user_id=$1 AND title_id=$2", user_id, title_id)
    if row:
        await execute("UPDATE user_titles SET copies=copies+1,last_obtained_at=$1 WHERE user_id=$2 AND title_id=$3",
                      now, user_id, title_id)
        return False
    await execute("INSERT INTO user_titles(user_id,title_id,copies,first_obtained_at,last_obtained_at) "
                  "VALUES ($1,$2,1,$3,$3)", user_id, title_id, now)
    return True


async def draw(user: dict, body: dict) -> dict:
    ticket_type = body.get("ticket_type")
    request_id = body.get("request_id")
    if ticket_type not in TICKET_TYPES:
        raise APIError("券类型须为 single / ten / hundred")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise APIError("抽卡请求编号格式错误")
    count = TICKET_DRAWS[ticket_type]
    now = timeutil.now()
    async with write_txn():
        existing = await fetch_one("SELECT * FROM title_draw_batches WHERE user_id=$1 AND request_id=$2",
                                   user["id"], request_id)
        if existing:
            if existing["ticket_type"] != ticket_type:
                raise APIError("抽卡请求编号已用于其他券型", 409)
            return await _batch_result(user["id"], existing)
        state = await _state(user["id"])
        if int(state[TICKET_COL[ticket_type]]) < 1:
            raise APIError("该券不足，请先购买", 400)
        pools = await _load_pools()
        if not pools.get("N") and not pools.get("R") and not pools.get("SR"):
            raise APIError("卡池暂未配置", 503)
        batch_id = next_id()
        await execute("INSERT INTO title_draw_batches(id,user_id,request_id,ticket_type,count,created_at) "
                      "VALUES ($1,$2,$3,$4,$5,$6)", batch_id, user["id"], request_id, ticket_type, count, now)
        pity = int(state["pity"])
        results: list[dict] = []
        for i in range(count):
            pity_before = pity
            pity += 1
            rarity = _choose_rarity(pity, pools)
            if rarity == "SSR":
                pity = 0
            results.append({"rarity": rarity, "pity_before": pity_before})
        # 每 10 抽区块 SR 保底（最后一抽强制 SR；若已是 SSR 保留）
        for block_start in range(0, count, 10):
            block = results[block_start:block_start + 10]
            if block and all(item["rarity"] in ("N", "R") for item in block) and pools.get("SR"):
                block[-1]["rarity"] = "SR"
        serialized: list[dict] = []
        for item in results:
            pool = pools.get(item["rarity"]) or []
            if not pool:
                raise APIError("卡池配置缺少可用稀有度", 503)
            picked = _pick_weighted(pool)
            is_new = await _give_title(user["id"], picked["id"], now)
            await execute(
                "INSERT INTO title_draws(id,batch_id,user_id,title_id,rarity,is_new,pity_before,created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                next_id(), batch_id, user["id"], picked["id"], item["rarity"], int(is_new),
                item["pity_before"], now)
            serialized.append({"title_id": picked["id"], "rarity": item["rarity"], "is_new": is_new})
        await _ticket_apply(user["id"], ticket_type, -1, "draw", str(batch_id), now)
        await execute("UPDATE user_title_state SET pity=$1,total_draws=total_draws+$2 WHERE user_id=$3",
                      pity, count, user["id"])
        state = await _state(user["id"])
    return {"batch": {"id": batch_id, "ticket_type": ticket_type, "count": count},
            "results": serialized, "pity": int(state["pity"]), "pity_limit": PITY_LIMIT,
            "tickets": _tickets_of(state)}


async def _batch_result(user_id: str, batch: dict) -> dict:
    rows = await fetch("SELECT title_id,rarity,is_new FROM title_draws WHERE batch_id=$1 ORDER BY id", batch["id"])
    state = await _state(user_id)
    return {"batch": {"id": batch["id"], "ticket_type": batch["ticket_type"], "count": batch["count"]},
            "results": [{"title_id": r["title_id"], "rarity": r["rarity"], "is_new": bool(r["is_new"])} for r in rows],
            "pity": int(state["pity"]), "pity_limit": PITY_LIMIT, "tickets": _tickets_of(state)}


# ── 购券 ──────────────────────────────────────────────────────────────────────

async def purchase_ticket(user: dict, body: dict) -> dict:
    product_id, request_id = body.get("product_id"), body.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise APIError("购券请求编号格式错误")
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        raise APIError("请选择有效的券商品") from None
    now = timeutil.now()
    day = timeutil.day_key(now)
    async with write_txn():
        existing = await fetch_one("SELECT * FROM shop_purchases WHERE user_id=$1 AND request_id=$2",
                                   user["id"], request_id)
        if existing:
            if int(existing["product_id"]) != product_id:
                raise APIError("购券请求编号已用于其他商品", 409)
            return await _purchase_result(user["id"], existing)
        product = await fetch_one("SELECT * FROM shop_products WHERE id=$1", product_id)
        if not product or not product["is_active"] or product["category"] != "TICKET":
            raise APIError("券商品不存在或已下架", 404)
        draw_count = int(product["draw_count"])
        ticket_type = DRAW_TO_TICKET.get(draw_count)
        if ticket_type is None:
            raise APIError("券商品配置错误", 503)
        order_no = f"TO-{day.replace('-', '')}-{secrets.token_hex(6).upper()}"
        await credits.spend_points(user, int(product["points_price"]), "ticket_purchase", order_no, now)
        await _ticket_apply(user["id"], ticket_type, 1, "purchase", order_no, now)
        await execute(
            "INSERT INTO shop_purchases(order_no,product_id,category,product_name,user_id,username,points_cost,"
            "ldc_amount,status,trade_no,error,created_at,day,request_id,draw_count) "
            "VALUES ($1,$2,'TICKET',$3,$4,$5,$6,'0.00','success','','',$7,$8,$9,$10)",
            order_no, product_id, product["name"], user["id"], user["username"], product["points_price"],
            now, day, request_id, draw_count)
        order = await fetch_one("SELECT * FROM shop_purchases WHERE order_no=$1", order_no)
        state = await _state(user["id"])
        wallet = await credits.wallet_view(user["id"])
    return {"order": _order_view(order), "status": "success", "ticket_type": ticket_type,
            "tickets": _tickets_of(state), "wallet": wallet}


async def _purchase_result(user_id: str, order: dict) -> dict:
    state = await _state(user_id)
    ticket_type = DRAW_TO_TICKET.get(int(order["draw_count"]))
    return {"order": _order_view(order), "status": order["status"], "ticket_type": ticket_type,
            "tickets": _tickets_of(state), "wallet": await credits.wallet_view(user_id)}


def _order_view(order: dict) -> dict:
    return {"order_no": order["order_no"], "category": order["category"], "product_id": order["product_id"],
            "product_name": order["product_name"], "points_cost": order["points_cost"],
            "draw_count": order.get("draw_count", 0), "status": order["status"],
            "created_at": timeutil.iso_time(order["created_at"])}


# ── 熔炼 / 合成 ───────────────────────────────────────────────────────────────

def _norm_materials(materials: Any) -> list[dict]:
    if not isinstance(materials, list) or not materials:
        raise APIError("请选择熔炼材料")
    merged: dict[int, int] = {}
    for item in materials:
        if not isinstance(item, dict):
            raise APIError("熔炼材料格式错误")
        try:
            title_id, count = int(item.get("title_id")), int(item.get("count"))
        except (TypeError, ValueError):
            raise APIError("熔炼材料格式错误") from None
        if count <= 0:
            raise APIError("熔炼材料数量须为正整数")
        merged[title_id] = merged.get(title_id, 0) + count
    return [{"title_id": k, "count": v} for k, v in merged.items()]


async def _consume(user_id: str, title_id: int, count: int, equipped: int | None) -> None:
    row = await fetch_one("SELECT copies FROM user_titles WHERE user_id=$1 AND title_id=$2", user_id, title_id)
    if not row:
        raise APIError("材料称号不存在", 404)
    keep = 1 if equipped == title_id else 0
    if int(row["copies"]) - count < keep:
        raise APIError("材料称号副本不足（装备中的称号至少保留 1 张）", 409)
    remaining = int(row["copies"]) - count
    if remaining <= 0:
        await execute("DELETE FROM user_titles WHERE user_id=$1 AND title_id=$2", user_id, title_id)
    else:
        await execute("UPDATE user_titles SET copies=$1 WHERE user_id=$2 AND title_id=$3", remaining, user_id, title_id)


async def smelt(user: dict, body: dict) -> dict:
    mode, input_rarity, request_id = body.get("mode"), body.get("input_rarity"), body.get("request_id")
    if mode not in ("random", "target"):
        raise APIError("熔炼模式须为 random 或 target")
    if input_rarity not in SMELT_COST:
        raise APIError("熔炼稀有度须为 N / R / SR")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise APIError("熔炼请求编号格式错误")
    cost = SMELT_COST[input_rarity][mode]
    materials = _norm_materials(body.get("materials"))
    if sum(m["count"] for m in materials) != cost:
        raise APIError(f"该熔炼需 {cost} 张 {input_rarity} 材料")
    output_rarity = NEXT_RARITY[input_rarity]
    now = timeutil.now()
    async with write_txn():
        existing = await fetch_one("SELECT * FROM title_crafts WHERE user_id=$1 AND request_id=$2",
                                   user["id"], request_id)
        if existing:
            return await _craft_result(user["id"], existing)
        state = await _state(user["id"])
        equipped = state["equipped_title_id"]
        for m in materials:
            row = await fetch_one("SELECT rarity FROM title_defs WHERE id=$1", m["title_id"])
            if not row or row["rarity"] != input_rarity:
                raise APIError("材料必须为同稀有度称号")
        if mode == "target":
            target = body.get("target_title_id")
            try:
                target_id = int(target)
            except (TypeError, ValueError):
                raise APIError("请选择定向熔炼目标") from None
            target_row = await fetch_one("SELECT id FROM title_defs WHERE id=$1 AND rarity=$2 AND is_active=1",
                                         target_id, output_rarity)
            if not target_row:
                raise APIError("定向目标不存在或不可用", 404)
        else:
            target_id = None
        for m in materials:
            await _consume(user["id"], m["title_id"], m["count"], int(equipped) if equipped else None)
        if mode == "random":
            owned = {r["title_id"] for r in await fetch(
                "SELECT title_id FROM user_titles WHERE user_id=$1", user["id"])}
            candidates = [r for r in await fetch(
                "SELECT id,weight FROM title_defs WHERE rarity=$1 AND is_active=1", output_rarity)]
            fresh = [r for r in candidates if r["id"] not in owned]
            target_id = _pick_weighted(fresh if fresh else candidates)["id"]
        is_new = await _give_title(user["id"], target_id, now)
        craft_id = next_id()
        await execute(
            "INSERT INTO title_crafts(id,user_id,kind,input_rarity,output_title_id,materials,request_id,created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)",
            craft_id, user["id"], f"smelt_{mode}", input_rarity, target_id,
            json.dumps(materials, ensure_ascii=False), request_id, now)
        craft = await fetch_one("SELECT * FROM title_crafts WHERE id=$1", craft_id)
    return {"kind": craft["kind"],
            "output": {"title_id": target_id, "rarity": output_rarity, "is_new": is_new},
            "consumed": materials, "collection": {"copies": 1}}


async def craft_ur(user: dict, body: dict) -> dict:
    recipe_id, request_id = body.get("recipe_id"), body.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise APIError("合成请求编号格式错误")
    recipes = await _config("ur_recipes", [])
    recipe = next((r for r in recipes if isinstance(r, dict) and str(r.get("id")) == str(recipe_id)), None)
    if not recipe:
        raise APIError("UR 配方不存在", 404)
    material_codes = recipe.get("materials") or []
    output_code = recipe.get("output_code")
    if len(material_codes) != 3 or not output_code:
        raise APIError("UR 配方配置错误", 503)
    materials = _norm_materials(body.get("materials"))
    now = timeutil.now()
    async with write_txn():
        existing = await fetch_one("SELECT * FROM title_crafts WHERE user_id=$1 AND request_id=$2",
                                   user["id"], request_id)
        if existing:
            return await _craft_result(user["id"], existing)
        ur = await fetch_one("SELECT id FROM title_defs WHERE code=$1 AND rarity='UR'", output_code)
        if not ur:
            raise APIError("UR 卡位不存在", 503)
        if await fetch_one("SELECT 1 FROM user_titles WHERE user_id=$1 AND title_id=$2", user["id"], ur["id"]):
            raise APIError("已拥有该 UR，不能重复合成", 409)
        required = {}
        for code in material_codes:
            row = await fetch_one("SELECT id FROM title_defs WHERE code=$1 AND rarity='SSR'", code)
            if not row:
                raise APIError("UR 配方材料卡位不存在", 503)
            required[row["id"]] = required.get(row["id"], 0) + 1
        provided = {m["title_id"]: m["count"] for m in materials}
        if provided != required:
            raise APIError("UR 合成材料与配方不一致", 409)
        state = await _state(user["id"])
        equipped = state["equipped_title_id"]
        for title_id, cnt in required.items():
            await _consume(user["id"], title_id, cnt, int(equipped) if equipped else None)
        is_new = await _give_title(user["id"], ur["id"], now)
        craft_id = next_id()
        await execute(
            "INSERT INTO title_crafts(id,user_id,kind,input_rarity,output_title_id,materials,request_id,created_at) "
            "VALUES ($1,$2,'ur',NULL,$3,$4::jsonb,$5,$6)",
            craft_id, user["id"], ur["id"], json.dumps(materials, ensure_ascii=False), request_id, now)
        craft = await fetch_one("SELECT * FROM title_crafts WHERE id=$1", craft_id)
    return {"kind": "ur", "output": {"title_id": ur["id"], "rarity": "UR", "is_new": is_new},
            "consumed": materials, "collection": {"copies": 1}}


async def _craft_result(user_id: str, craft: dict) -> dict:
    output = await fetch_one("SELECT id,rarity FROM title_defs WHERE id=$1", craft["output_title_id"])
    materials = craft["materials"]
    if isinstance(materials, str):
        materials = json.loads(materials)
    return {"kind": craft["kind"],
            "output": {"title_id": craft["output_title_id"], "rarity": output["rarity"], "is_new": False},
            "consumed": materials, "collection": {"copies": 1}}


# ── 装备 ──────────────────────────────────────────────────────────────────────

async def equip(user: dict, body: dict) -> dict:
    title_id = body.get("title_id")
    now = timeutil.now()
    async with write_txn():
        await _ensure_state(user["id"])
        if title_id is None:
            await execute("UPDATE user_title_state SET equipped_title_id=NULL WHERE user_id=$1", user["id"])
        else:
            try:
                title_id = int(title_id)
            except (TypeError, ValueError):
                raise APIError("称号编号不正确") from None
            if not await fetch_one("SELECT 1 FROM user_titles WHERE user_id=$1 AND title_id=$2",
                                   user["id"], title_id):
                raise APIError("尚未拥有该称号", 409)
            await execute("UPDATE user_title_state SET equipped_title_id=$1 WHERE user_id=$2", title_id, user["id"])
        state = await _state(user["id"])
    return {"equipped_title_id": state["equipped_title_id"]}


# ── 查询视图 ──────────────────────────────────────────────────────────────────

async def title_view(user: dict | None) -> dict:
    defs = await fetch(
        "SELECT d.id,d.code,d.rarity,d.weight,d.discount_bp,d.is_active,d.is_limited,d.is_smeltable,"
        "c.name,c.description,c.icon,c.route FROM title_defs d "
        "LEFT JOIN title_content c ON c.title_id=d.id WHERE d.is_active=1 ORDER BY d.rarity,d.id")
    owned = {}
    equipped = None
    tickets = {t: 0 for t in TICKET_TYPES}
    pity = 0
    if user:
        owned = {int(r["title_id"]): int(r["copies"]) for r in await fetch(
            "SELECT title_id,copies FROM user_titles WHERE user_id=$1", user["id"])}
        state = await _state(user["id"])
        equipped = state["equipped_title_id"]
        tickets = _tickets_of(state)
        pity = int(state["pity"])
    collection = []
    for row in defs:
        item = dict(row)
        item["copies"] = owned.get(int(row["id"]), 0)
        item["owned"] = item["copies"] > 0
        collection.append(item)
    products = await fetch(
        "SELECT id,name,description,points_price,draw_count FROM shop_products "
        "WHERE category='TICKET' AND is_active=1 ORDER BY draw_count")
    recipes = await _config("ur_recipes", [])
    return {"user": user, "tickets": tickets, "pity": pity, "pity_limit": PITY_LIMIT,
            "equipped_title_id": equipped, "collection": collection,
            "ticket_products": products, "recipes": recipes,
            "wallet": await credits.wallet_view(user["id"]) if user else None,
            "history": await history(user["id"]) if user else {"draws": [], "crafts": []}}


async def history(user_id: str) -> dict:
    draws = await fetch(
        "SELECT id,title_id,rarity,is_new,created_at FROM title_draws WHERE user_id=$1 ORDER BY id DESC LIMIT 50",
        user_id)
    for row in draws:
        row["created_at"] = timeutil.iso_time(row["created_at"])
        row["is_new"] = bool(row["is_new"])
    crafts = await fetch(
        "SELECT id,kind,input_rarity,output_title_id,materials,created_at FROM title_crafts "
        "WHERE user_id=$1 ORDER BY id DESC LIMIT 50", user_id)
    for row in crafts:
        row["created_at"] = timeutil.iso_time(row["created_at"])
        if isinstance(row["materials"], str):
            row["materials"] = json.loads(row["materials"])
    return {"draws": draws, "crafts": crafts}


# ── 管理 ──────────────────────────────────────────────────────────────────────

async def admin_list() -> dict:
    defs = await fetch(
        "SELECT d.id,d.code,d.rarity,d.weight,d.discount_bp,d.is_active,d.is_limited,d.is_smeltable,"
        "c.name,c.description,c.icon,c.route FROM title_defs d "
        "LEFT JOIN title_content c ON c.title_id=d.id ORDER BY d.rarity,d.id")
    stats = await admin_stats()
    return {"titles": defs, "stats": stats}


async def admin_save(body: dict) -> dict:
    code = body.get("code")
    rarity = body.get("rarity")
    if not isinstance(code, str) or not _CODE_RE.fullmatch(code):
        raise APIError("卡位 code 须为 1–40 位字母数字/下划线/中划线")
    if rarity not in RARITIES:
        raise APIError("稀有度不正确")
    try:
        weight = int(body.get("weight", 1))
        discount_bp = int(body.get("discount_bp", 10000))
    except (TypeError, ValueError):
        raise APIError("权重/折扣参数不正确") from None
    if weight <= 0:
        raise APIError("权重须为正整数")
    if not 9000 <= discount_bp <= 10000:
        raise APIError("折扣须在 9000–10000")
    is_smeltable = 0 if rarity == "UR" else (1 if body.get("is_smeltable", True) else 0)
    flags = {"is_active": 1 if body.get("is_active", True) else 0,
             "is_limited": 1 if body.get("is_limited", False) else 0}
    name = body.get("name", "")
    if not isinstance(name, str) or len(name) > 80:
        raise APIError("称号名称最多 80 字")
    description = body.get("description", "") or ""
    if not isinstance(description, str) or len(description) > 500:
        raise APIError("称号描述最多 500 字")
    icon = body.get("icon", "") or ""
    route = body.get("route", "") or ""
    now = timeutil.now()
    async with write_txn():
        raw_id = body.get("id")
        if raw_id in (None, ""):
            title_id = next_id()
            await execute(
                "INSERT INTO title_defs(id,code,rarity,weight,discount_bp,is_active,is_limited,is_smeltable,created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                title_id, code, rarity, weight, discount_bp, flags["is_active"], flags["is_limited"],
                is_smeltable, now)
        else:
            try:
                title_id = int(raw_id)
            except (TypeError, ValueError):
                raise APIError("卡位编号不正确") from None
            changed = await execute(
                "UPDATE title_defs SET code=$1,rarity=$2,weight=$3,discount_bp=$4,is_active=$5,is_limited=$6,"
                "is_smeltable=$7 WHERE id=$8",
                code, rarity, weight, discount_bp, flags["is_active"], flags["is_limited"], is_smeltable, title_id)
            if not changed:
                raise APIError("卡位不存在", 404)
        await execute(
            "INSERT INTO title_content(title_id,name,description,icon,route,source_type,updated_at) "
            "VALUES ($1,$2,$3,$4,$5,'generated',$6) ON CONFLICT(title_id) DO UPDATE SET "
            "name=excluded.name,description=excluded.description,icon=excluded.icon,route=excluded.route,"
            "updated_at=excluded.updated_at",
            title_id, name, description, icon, route, now)
    return {"title_id": title_id, "code": code}


async def admin_grant(body: dict) -> dict:
    user_id = body.get("user_id")
    if not isinstance(user_id, str) or not user_id.isascii() or not user_id.isdecimal():
        raise APIError("请选择有效用户")
    try:
        count = int(body.get("count"))
    except (TypeError, ValueError):
        raise APIError("数量不正确") from None
    if count == 0:
        raise APIError("数量不能为 0")
    title_id = body.get("title_id")
    code = body.get("code")
    now = timeutil.now()
    async with write_txn():
        if title_id in (None, "") and isinstance(code, str):
            row = await fetch_one("SELECT id FROM title_defs WHERE code=$1", code)
            if not row:
                raise APIError("卡位不存在", 404)
            title_id = row["id"]
        try:
            title_id = int(title_id)
        except (TypeError, ValueError):
            raise APIError("卡位编号不正确") from None
        if not await fetch_one("SELECT 1 FROM title_defs WHERE id=$1", title_id):
            raise APIError("卡位不存在", 404)
        if count > 0:
            await _give_title(user_id, title_id, now)
            for _ in range(count - 1):
                await execute("UPDATE user_titles SET copies=copies+1 WHERE user_id=$1 AND title_id=$2",
                              user_id, title_id)
        else:
            state = await _state(user_id)
            row = await fetch_one("SELECT copies FROM user_titles WHERE user_id=$1 AND title_id=$2",
                                  user_id, title_id)
            current = int(row["copies"]) if row else 0
            keep = 1 if state["equipped_title_id"] == title_id else 0
            remaining = current + count
            if remaining < keep:
                raise APIError("收回后数量不足（装备中的称号至少保留 1 张）", 409)
            if remaining <= 0:
                await execute("DELETE FROM user_titles WHERE user_id=$1 AND title_id=$2", user_id, title_id)
            else:
                await execute("UPDATE user_titles SET copies=$1 WHERE user_id=$2 AND title_id=$3",
                              remaining, user_id, title_id)
        row = await fetch_one("SELECT copies FROM user_titles WHERE user_id=$1 AND title_id=$2", user_id, title_id)
    return {"user_id": user_id, "title_id": title_id, "copies": int(row["copies"]) if row else 0}


async def admin_stats() -> dict:
    per_rarity = {r: 0 for r in RARITIES}
    for row in await fetch("SELECT rarity,COUNT(*) AS n FROM title_defs GROUP BY rarity"):
        per_rarity[row["rarity"]] = int(row["n"])
    draws = (await fetch_one("SELECT COUNT(*) AS n FROM title_draws"))["n"]
    ur_holders = (await fetch_one(
        "SELECT COUNT(DISTINCT ut.user_id) AS n FROM user_titles ut "
        "JOIN title_defs d ON d.id=ut.title_id WHERE d.rarity='UR'"))["n"]
    return {"defs_per_rarity": per_rarity, "total_draws": int(draws), "ur_holders": int(ur_holders)}


async def admin_save_config(body: dict) -> dict:
    result = {}
    if "smelt_costs" in body:
        result["smelt_costs"] = body["smelt_costs"]
    if "ur_recipes" in body:
        recipes = body["ur_recipes"]
        if not isinstance(recipes, list):
            raise APIError("UR 配方须为列表")
        for r in recipes:
            if (not isinstance(r, dict) or not r.get("id") or not r.get("output_code")
                    or not isinstance(r.get("materials"), list) or len(r["materials"]) != 3):
                raise APIError("UR 配方格式错误（需 id、output_code、3 个 materials）")
        result["ur_recipes"] = recipes
    for key, value in result.items():
        await set_config(key, value)
    return {"saved": list(result)}
