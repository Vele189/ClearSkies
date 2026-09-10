import random

import pytest

from pipeline.policy import (
    PartialFailurePolicy,
    RateLimit,
    RetryPolicy,
    Throttle,
    Verdict,
)
from tests.conftest import FakeClock

NO_JITTER = RetryPolicy(jitter=0.0)


def test_backoff_doubles_from_the_initial_wait() -> None:
    assert [NO_JITTER.backoff_for(n) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped() -> None:
    policy = RetryPolicy(jitter=0.0, max_backoff_s=5.0)
    assert policy.backoff_for(10) == 5.0


def test_jitter_only_ever_shortens_the_wait() -> None:
    # Five adapters starting together in the nightly job must not retry in step.
    policy = RetryPolicy(jitter=0.25)
    rng = random.Random(7)
    waits = [policy.backoff_for(2, rng=rng) for _ in range(50)]
    assert all(1.5 <= w <= 2.0 for w in waits)
    assert len(set(waits)) > 1


def test_retry_after_wins_over_computed_backoff() -> None:
    assert NO_JITTER.backoff_for(1, retry_after=12.0) == 12.0


def test_an_absurd_retry_after_is_clamped() -> None:
    policy = RetryPolicy(max_retry_after_s=300.0)
    assert policy.backoff_for(1, retry_after=86_400.0) == 300.0


def test_gives_up_after_max_attempts() -> None:
    policy = RetryPolicy(max_attempts=3)
    assert not policy.gives_up_after(2)
    assert policy.gives_up_after(3)


@pytest.mark.parametrize(
    ("accepted", "rejected", "expected"),
    [
        (100, 0, "ok"),
        (100, 1, "partial"),
        (100, 2, "failed"),
        (0, 5, "failed"),
        (0, 0, "failed"),
    ],
)
def test_partial_failure_verdicts(accepted: int, rejected: int, expected: Verdict) -> None:
    assert PartialFailurePolicy().verdict(accepted=accepted, rejected=rejected) == expected


def test_absolute_reject_ceiling_beats_the_fraction() -> None:
    policy = PartialFailurePolicy(max_reject_fraction=0.5, max_rejects=10)
    assert policy.verdict(accepted=1000, rejected=11) == "failed"


def test_min_records_rejects_a_suspiciously_empty_pull() -> None:
    policy = PartialFailurePolicy(min_records=500)
    assert policy.verdict(accepted=499, rejected=0) == "failed"


async def test_throttle_spaces_requests_at_the_configured_rate() -> None:
    clock = FakeClock()
    throttle = Throttle(
        RateLimit(requests_per_second=2.0, burst=1),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    for _ in range(3):
        await throttle.acquire()
    assert clock.slept == [0.5, 0.5]


async def test_throttle_spends_its_burst_before_waiting() -> None:
    clock = FakeClock()
    throttle = Throttle(
        RateLimit(requests_per_second=1.0, burst=3),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    for _ in range(3):
        await throttle.acquire()
    assert clock.slept == []


async def test_unlimited_never_sleeps() -> None:
    clock = FakeClock()
    throttle = Throttle(RateLimit.unlimited(), monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(10):
        assert await throttle.acquire() == 0.0
    assert clock.slept == []
