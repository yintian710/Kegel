from __future__ import annotations

import asyncio

import pytest

from app.infrastructure.database import execute, fetch

pytestmark = pytest.mark.asyncio(loop_scope="session")


def upload(clock, suffix, **changes):
    repetitions = changes.get("repetitions", 2)
    interval = changes.get("interval_seconds", 2)
    ended_at = changes.get("ended_at", int(clock.value * 1000))
    body = {"round_id": f"training-round-{suffix}", "started_at": ended_at - repetitions * interval * 1000,
            "ended_at": ended_at, "repetitions": repetitions, "interval_seconds": interval, "mode": "auto"}
    body.update(changes)
    return body


async def test_upload_requires_login_but_reading_is_public(client):
    code, guest = await client.request("/api/practice")
    assert code == 200
    assert set(guest) == {"user", "oauth_ready", "day", "leaderboard", "total_leaderboard", "records"}
    assert (await client.request("/api/practice/records", upload(client.clock, "anon0000001")))[0] == 401
    body = upload(client.clock, "identity00001", expected_user_id="2")
    code, message = await client.request("/api/practice/records", body, user=1)
    assert code == 409 and "切换" in message


async def test_upload_counts_ranks_and_is_idempotent(client):
    assert (await client.request("/api/practice/records", upload(client.clock, "count-user1-0001", repetitions=3), user=1))[0] == 200
    assert (await client.request("/api/practice/records", upload(client.clock, "count-user2-0001", repetitions=5), user=2))[0] == 200
    _, board = await client.request("/api/practice")
    assert [(row["rank"], row["username"], row["count"]) for row in board["leaderboard"]] == [(1, "user2", 5), (2, "user1", 3)]
    body = upload(client.clock, "idempotent-00001")
    assert (await client.request("/api/practice/records", body, user=3))[0] == 200
    assert (await client.request("/api/practice/records", body, user=3))[0] == 200
    changed = {**body, "repetitions": 1}
    assert (await client.request("/api/practice/records", changed, user=3))[0] == 409
    assert len(await fetch("SELECT 1 FROM training_records WHERE user_id='3'")) == 1
    # 同一轮编号对不同用户互相独立。
    assert (await client.request("/api/practice/records", body, user=4))[0] == 200


async def test_total_board_spans_days_and_personal_history_is_limited(client):
    first = upload(client.clock, "total-first-user1", repetitions=5)
    assert (await client.request("/api/practice/records", first, user=1))[0] == 200
    client.clock.advance(86400)
    second = upload(client.clock, "total-second-user1", repetitions=2)
    assert (await client.request("/api/practice/records", second, user=1))[0] == 200
    _, board = await client.request("/api/practice", user=1)
    assert board["leaderboard"][0]["count"] == 2
    assert board["total_leaderboard"][0]["count"] == 7
    for index in range(51):
        await execute("INSERT INTO training_records(id,user_id,username,day,round_id,started_at,ended_at,repetitions,"
                      "interval_seconds,mode,received_at) VALUES ($1,'9','user9','2026-10-27',$2,$3,$4,1,2,'auto',$5)",
                      10_000 + index, f"bulk-round-{index:08d}", index * 10, index * 10 + 5, index)
    assert len((await client.request("/api/practice", user=9))[1]["records"]) == 50


@pytest.mark.parametrize("change", [
    {"repetitions": 0}, {"repetitions": 21}, {"repetitions": True}, {"interval_seconds": 1}, {"interval_seconds": 11},
    {"mode": "turbo"}, {"round_id": "short"}, {"started_at": "x"}, {"ended_at": 1}, {"repetitions": 20, "interval_seconds": 10},
])
async def test_upload_validation(client, change):
    body = upload(client.clock, "validation-000001")
    body.update(change)
    assert (await client.request("/api/practice/records", body, user=1))[0] == 400


async def test_upload_time_bounds_and_overlap(client):
    now_ms = int(client.clock.value * 1000)
    stale = upload(client.clock, "stale-start-0001", ended_at=now_ms - 3_600_000 + 1000, repetitions=2)
    stale["started_at"] = now_ms - 3_600_001
    assert (await client.request("/api/practice/records", stale, user=1))[0] == 400
    assert (await client.request("/api/practice/records", upload(client.clock, "late-end-000001", ended_at=now_ms - 300_001), user=1))[0] == 400
    assert (await client.request("/api/practice/records", upload(client.clock, "future-0000001", ended_at=now_ms + 30_001), user=1))[0] == 400
    first = upload(client.clock, "overlap-first-01", ended_at=now_ms)
    assert (await client.request("/api/practice/records", first, user=1))[0] == 200
    overlapping = upload(client.clock, "overlap-second-1", ended_at=now_ms + 1000)
    assert (await client.request("/api/practice/records", overlapping, user=1))[0] == 409
    touching = upload(client.clock, "overlap-touch-01", ended_at=now_ms + 4000, repetitions=2)
    assert touching["started_at"] == first["ended_at"]
    assert (await client.request("/api/practice/records", touching, user=1))[0] == 200


async def test_concurrent_replays_and_overlaps_serialize(client):
    replay = upload(client.clock, "parallel-replay01")
    results = await asyncio.gather(*(client.request("/api/practice/records", replay, user=1) for _ in range(8)))
    assert all(code == 200 for code, _ in results)
    assert len(await fetch("SELECT 1 FROM training_records WHERE user_id='1'")) == 1
    now_ms = int(client.clock.value * 1000)
    bodies = [upload(client.clock, f"parallel-over-{i:03d}", ended_at=now_ms + 10_000 + i) for i in range(6)]
    results = await asyncio.gather(*(client.request("/api/practice/records", body, user=2) for body in bodies))
    assert sorted(code for code, _ in results) == [200] + [409] * 5


async def test_pending_review_blocks_upload_and_hides_from_board(client):
    await execute("INSERT INTO reviews(day,user_id,reason) VALUES ('2026-10-26','2','测试')")
    assert (await client.request("/api/practice/records", upload(client.clock, "blocked-0000001"), user=2))[0] == 403
