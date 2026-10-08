import threading
import time

import pytest

from app.control_plane.limits import (
    LimiterRegistry,
    ProviderLimiter,
    ProviderLimits,
    QueueFull,
    RateLimitTimeout,
    RunScheduler,
    TokenBucket,
)


class FakeClock:
    """Time that only moves when the test (or a sleeping bucket) says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def bucket(rate=10.0, capacity=10.0):
    c = FakeClock()
    return TokenBucket(rate, capacity, clock=c, sleep=c.sleep), c


# ---- token bucket --------------------------------------------------------------------------------------------
def test_a_full_bucket_allows_a_burst_then_refuses():
    b, _ = bucket(rate=1, capacity=5)
    assert [b.try_acquire() for _ in range(6)] == [True] * 5 + [False]


def test_the_bucket_refills_with_time_but_never_past_capacity():
    b, c = bucket(rate=2, capacity=4)
    assert b.try_acquire(4) and not b.try_acquire()
    c.now += 1.0
    assert b.available == pytest.approx(2.0) and b.try_acquire(2) and not b.try_acquire()
    c.now += 100
    assert b.available == 4  # capped


def test_acquire_waits_exactly_as_long_as_needed():
    b, c = bucket(rate=2, capacity=2)
    b.try_acquire(2)
    waited = b.acquire(1)
    assert waited == pytest.approx(0.5, abs=0.01) and c.now == pytest.approx(0.5, abs=0.01)


def test_acquire_gives_up_when_the_wait_would_exceed_the_timeout():
    b, c = bucket(rate=1, capacity=1)
    b.try_acquire()
    with pytest.raises(RateLimitTimeout):
        b.acquire(1, timeout=0.2)
    assert c.now < 0.5  # it did not wait out the full second


def test_a_request_larger_than_the_bucket_still_gets_through_after_a_full_refill():
    b, _ = bucket(rate=100, capacity=100)
    assert b.try_acquire(100_000) is True  # clamped to capacity: not stuck forever
    assert not b.try_acquire(100_000)


def test_invalid_buckets_are_rejected():
    for args in [(0, 1), (1, 0), (-1, 1)]:
        with pytest.raises(ValueError):
            TokenBucket(*args)


# ---- provider limiter ------------------------------------------------------------------------------------------------
def limiter(**over):
    c = FakeClock()
    lim = ProviderLimiter("azure_openai", ProviderLimits(**{"requests_per_minute": 60, "tokens_per_minute": 6000,
                                                            "max_concurrent": 2, "queue_timeout_sec": 5, **over}),
                          clock=c, sleep=c.sleep)
    return lim, c


def test_calls_within_limits_pass_straight_through():
    lim, _ = limiter()
    with lim.slot(100):
        assert lim.in_flight == 1
    assert lim.in_flight == 0 and lim.waits == 0


def test_the_request_rate_limit_makes_callers_wait_instead_of_hitting_the_provider_429():
    lim, c = limiter(requests_per_minute=60)  # one per second, burst of 60
    for _ in range(60):
        with lim.slot(1):
            pass
    t0 = c.now
    with lim.slot(1):
        pass  # the 61st must wait for a refill
    assert c.now - t0 == pytest.approx(1.0, abs=0.05) and lim.waits == 1


def test_the_token_rate_limit_counts_estimated_tokens():
    lim, c = limiter(tokens_per_minute=6000)  # 100 tokens/second
    with lim.slot(6000):
        pass
    t0 = c.now
    with lim.slot(300):
        pass
    assert c.now - t0 == pytest.approx(3.0, abs=0.1)


def test_a_caller_that_would_wait_too_long_is_refused_and_counted():
    lim, _ = limiter(requests_per_minute=1, queue_timeout_sec=2)
    with lim.slot(1):
        pass
    with pytest.raises(RateLimitTimeout), lim.slot(1):
        pass
    assert lim.rejections == 1 and lim.in_flight == 0  # nothing leaked


def test_concurrency_is_capped_and_a_third_caller_times_out():
    lim = ProviderLimiter("p", ProviderLimits(max_concurrent=2, queue_timeout_sec=0.2))
    entered, release = threading.Barrier(3), threading.Event()
    seen = []

    def hold():
        with lim.slot(1):
            seen.append(lim.in_flight)
            entered.wait(2)
            release.wait(2)

    ts = [threading.Thread(target=hold) for _ in range(2)]
    for t in ts:
        t.start()
    entered.wait(2)
    assert lim.in_flight == 2
    with pytest.raises(RateLimitTimeout, match="2 calls already in flight"), lim.slot(1):
        pass
    release.set()
    for t in ts:
        t.join(2)
    assert lim.in_flight == 0 and lim.rejections == 1


def test_a_failure_inside_the_slot_still_releases_it():
    lim = ProviderLimiter("p", ProviderLimits(max_concurrent=1, queue_timeout_sec=0.2))
    with pytest.raises(ValueError), lim.slot(1):
        raise ValueError("provider blew up")
    with lim.slot(1):  # the slot came back
        assert lim.in_flight == 1


def test_registry_gives_one_shared_limiter_per_provider_with_configured_limits():
    reg = LimiterRegistry({"azure_openai": {"max_concurrent": 3, "requests_per_minute": 120}})
    a = reg.for_provider("azure_openai")
    assert a is reg.for_provider("azure_openai") and a.limits.max_concurrent == 3 and a.limits.requests_per_minute == 120
    assert reg.for_provider("openai").limits.max_concurrent == 8  # defaults for unlisted providers
    assert set(reg.snapshots()) == {"azure_openai", "openai"}


# ---- run scheduler ----------------------------------------------------------------------------------------------------
def test_runs_start_immediately_up_to_the_limit_then_queue_in_order_then_are_refused():
    sched = RunScheduler(max_concurrent=2, max_queued=2)
    gate = threading.Event()
    order: list[int] = []

    def job(n):
        order.append(n)
        gate.wait(5)
        return n

    results = [sched.submit(job, i) for i in range(4)]
    assert [pos for _, pos in results] == [0, 0, 1, 2]  # two running, two waiting
    time.sleep(0.1)
    assert sched.snapshot() == {"running": 2, "queued": 2, "max_concurrent": 2, "max_queued": 2}
    with pytest.raises(QueueFull) as exc:
        sched.submit(job, 99)
    assert exc.value.retry_after_sec > 0
    gate.set()
    assert [f.result(5) for f, _ in results] == [0, 1, 2, 3]
    assert sorted(order) == [0, 1, 2, 3] and order.index(2) > 1  # waiting jobs ran after the first two started
    time.sleep(0.1)
    assert sched.snapshot()["running"] == 0 and sched.queued == 0


def test_a_failing_job_frees_its_slot_for_the_next_in_line():
    sched = RunScheduler(max_concurrent=1, max_queued=3)
    gate = threading.Event()

    def boom():
        gate.wait(5)
        raise RuntimeError("run crashed")

    f1, _ = sched.submit(boom)
    f2, pos = sched.submit(lambda: "second ran")
    assert pos == 1
    gate.set()
    with pytest.raises(RuntimeError):
        f1.result(5)
    assert f2.result(5) == "second ran"


def test_would_queue_reports_whether_the_next_run_must_wait():
    sched = RunScheduler(max_concurrent=1, max_queued=1)
    gate = threading.Event()
    assert sched.would_queue() is False
    sched.submit(gate.wait, 5)
    time.sleep(0.05)
    assert sched.would_queue() is True
    gate.set()
