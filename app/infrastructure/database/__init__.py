from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from tortoise import Tortoise, connections
from tortoise.transactions import in_transaction

from app.config import Settings

# 所有写事务先取同一把事务级咨询锁，复刻原 SQLite `BEGIN IMMEDIATE` 的串行化语义：
# 名次分配、余额扣减、限购计数等“先查后写”的逻辑不会在并发下交叉。
_WRITE_LOCK_KEY = 7_188_001


async def init_db() -> None:
    # uvicorn 的 lifespan 与请求跑在不同 asyncio 任务里，ContextVar 不互通，必须启用全局回退上下文。
    await Tortoise.init(
        db_url=Settings.DATABASE_URL,
        modules={"models": ["app.infrastructure.database.schemas"]},
        _enable_global_fallback=True,
    )
    if Settings.DB_AUTO_CREATE:  # 表结构只由 sql/schema.sql 交付，默认关闭
        await Tortoise.generate_schemas(safe=True)


async def close_db() -> None:
    await Tortoise.close_connections()


@asynccontextmanager
async def write_txn() -> AsyncIterator[Any]:
    """Serialized write transaction. Commits on exit, rolls back on any exception."""
    async with in_transaction() as connection:
        await connection.execute_query("SELECT pg_advisory_xact_lock($1)", [_WRITE_LOCK_KEY])
        yield connection


def _connection():
    return connections.get("default")


async def fetch(sql: str, *params: Any) -> list[dict[str, Any]]:
    """Run a read query on the active transaction (or the pool) and return dict rows."""
    return await _connection().execute_query_dict(sql, list(params))


async def fetch_one(sql: str, *params: Any) -> dict[str, Any] | None:
    rows = await fetch(sql, *params)
    return rows[0] if rows else None


async def execute(sql: str, *params: Any) -> int:
    """Run a statement and return the affected row count (reliable for UPDATE/DELETE only)."""
    affected, _ = await _connection().execute_query(sql, list(params))
    return affected
