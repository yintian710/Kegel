from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(timezone="UTC")


def setup(job, *, seconds: int = 1) -> None:
    """Register the periodic job and start the scheduler (call from lifespan startup)."""
    scheduler.add_job(job, "interval", seconds=seconds, id="checkin-tick",
                      max_instances=1, coalesce=True, replace_existing=True)
    scheduler.start()


def add_interval(job, *, job_id: str, seconds: int) -> None:
    """Register an extra periodic job (call after setup)."""
    scheduler.add_job(job, "interval", seconds=seconds, id=job_id,
                      max_instances=1, coalesce=True, replace_existing=True)


def teardown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
