import pytest

from rimex.presentation import ratelimit
from rimex.presentation.ratelimit import SlidingWindowLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(ratelimit.time, "monotonic", fake)
    return fake


def test_allows_up_to_limit(clock):
    limiter = SlidingWindowLimiter(limit=3, period=60)

    results = [limiter.hit(1) for _ in range(3)]

    assert results == [0, 0, 0]


def test_rejects_over_limit_with_retry_after(clock):
    limiter = SlidingWindowLimiter(limit=3, period=60)
    for _ in range(3):
        limiter.hit(1)

    clock.now += 20
    retry_after = limiter.hit(1)

    assert retry_after == 41


def test_users_are_independent(clock):
    limiter = SlidingWindowLimiter(limit=1, period=60)

    assert limiter.hit(1) == 0
    assert limiter.hit(1) > 0
    assert limiter.hit(2) == 0


def test_window_slides(clock):
    limiter = SlidingWindowLimiter(limit=2, period=60)
    limiter.hit(1)
    clock.now += 30
    limiter.hit(1)

    clock.now += 30
    assert limiter.hit(1) == 0

    assert limiter.hit(1) > 0


def test_rejected_requests_do_not_extend_block(clock):
    limiter = SlidingWindowLimiter(limit=1, period=60)
    limiter.hit(1)

    for _ in range(10):
        clock.now += 5
        limiter.hit(1)

    clock.now += 10
    assert limiter.hit(1) == 0
