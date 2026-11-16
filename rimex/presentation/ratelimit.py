import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, period: float) -> None:
        self.limit = limit
        self.period = period
        self._hits: dict[int, deque[float]] = {}

    def hit(self, key: int) -> int:
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.period:
            hits.popleft()
        if len(hits) >= self.limit:
            return int(self.period - (now - hits[0])) + 1
        hits.append(now)
        return 0
