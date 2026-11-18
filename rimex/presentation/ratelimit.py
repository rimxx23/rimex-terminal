import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, period: float) -> None:
        self.limit = limit
        self.period = period
        self._hits: dict[int | str, deque[float]] = {}

    def hit(self, key: int | str) -> int:
        now = time.monotonic()
        if key not in self._hits and len(self._hits) >= 10_000:
            self._hits = {
                identity: hits for identity, hits in self._hits.items()
                if hits and now - hits[-1] < self.period
            }
            if len(self._hits) >= 10_000:
                return max(1, int(self.period))
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.period:
            hits.popleft()
        if len(hits) >= self.limit:
            return int(self.period - (now - hits[0])) + 1
        hits.append(now)
        return 0
