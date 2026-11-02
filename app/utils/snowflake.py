from __future__ import annotations

import threading
import time

from app.config import Settings

EPOCH_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z
_WORKER_BITS = 10
_SEQUENCE_BITS = 12
_SEQUENCE_MASK = (1 << _SEQUENCE_BITS) - 1


class Snowflake:
    def __init__(self, worker_id: int):
        if not 0 <= worker_id < (1 << _WORKER_BITS):
            raise ValueError("SNOWFLAKE_WORKER_ID 须为 0–1023")
        self._worker = worker_id << _SEQUENCE_BITS
        self._lock = threading.Lock()
        self._last = -1
        self._sequence = 0

    def next_id(self) -> int:
        with self._lock:
            stamp = int(time.time() * 1000) - EPOCH_MS
            if stamp < self._last:
                stamp = self._last  # clock stepped back: keep ids monotonic
            if stamp == self._last:
                self._sequence = (self._sequence + 1) & _SEQUENCE_MASK
                if self._sequence == 0:
                    stamp += 1
            else:
                self._sequence = 0
            self._last = stamp
            return (stamp << (_WORKER_BITS + _SEQUENCE_BITS)) | self._worker | self._sequence


_generator: Snowflake | None = None


def next_id() -> int:
    global _generator
    if _generator is None:
        _generator = Snowflake(Settings.SNOWFLAKE_WORKER_ID)
    return _generator.next_id()
