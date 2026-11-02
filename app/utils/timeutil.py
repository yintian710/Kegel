from __future__ import annotations

import time

import arrow

from app.config import Settings


def now() -> float:
    """Wall-clock epoch seconds; the single seam tests replace to control time."""
    return time.time()


def _local(stamp: float) -> arrow.Arrow:
    return arrow.get(stamp).to(Settings.SITE_TZ_NAME)


def day_key(stamp: float | None = None) -> str:
    return _local(now() if stamp is None else stamp).format("YYYY-MM-DD")


def clock_hhmm(stamp: float) -> str:
    return _local(stamp).format("HH:mm")


def iso_time(stamp: float | None) -> str | None:
    return _local(stamp).datetime.isoformat(timespec="seconds") if stamp is not None else None


def iso_utc(stamp: float | None) -> str | None:
    return arrow.get(stamp).datetime.isoformat(timespec="seconds") if stamp is not None else None
