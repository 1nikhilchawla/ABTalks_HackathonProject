"""In-process sliding-window rate limiter.

Single-node only, which is right for a hackathon deployment; the interface is
small enough to be re-pointed at Redis without touching call sites.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int, burst_window: float = 60.0) -> None:
        self.per_minute = max(1, per_minute)
        self.window = burst_window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.per_minute:
                retry = int(self.window - (now - bucket[0])) + 1
                return False, max(retry, 1)
            bucket.append(now)
            if len(self._hits) > 5000:
                self._evict(cutoff)
            return True, 0

    def _evict(self, cutoff: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
        for k in stale:
            self._hits.pop(k, None)
