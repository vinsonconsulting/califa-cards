"""v0.7.0 eval rate-limit resilience: the reliability layer (offline, deterministic).

The pacer, the retry wrapper and the stats accumulator are pure and fully
injectable -- clock, sleep and jitter are all parameters -- so these exercise the
real backoff/pacing/accounting logic with ZERO ``claude`` calls and no wall-clock
sleeps. Jitter is pinned per test so backoff is asserted exactly; in production it
is ``random.uniform`` and only ever shapes a sleep duration, never a sample choice.
"""

import pytest

from skillcard.harness.reliability import (
    ReliabilityStats,
    TokenBucket,
    call_with_retry,
    parse_retry_after,
)

# --- ReliabilityStats: accumulate, max the backoff, merge two runs ---


def test_stats_as_dict_has_the_provenance_keys():
    d = ReliabilityStats().as_dict()
    assert set(d) == {
        "total_retries", "cumulative_wait_s", "max_backoff_s",
        "pacer_wait_count", "pacer_wait_s", "terminal_failures",
    }
    assert d["total_retries"] == 0 and d["terminal_failures"] == 0


def test_stats_merge_sums_counts_but_maxes_backoff():
    a = ReliabilityStats(total_retries=2, cumulative_wait_s=3.0, max_backoff_s=4.0,
                         pacer_wait_count=1, pacer_wait_s=1.0, terminal_failures=1)
    b = ReliabilityStats(total_retries=3, cumulative_wait_s=5.0, max_backoff_s=2.0,
                         pacer_wait_count=2, pacer_wait_s=2.0, terminal_failures=0)
    m = a.merge(b)
    assert m.total_retries == 5
    assert m.cumulative_wait_s == 8.0
    assert m.max_backoff_s == 4.0          # max, NOT sum
    assert m.pacer_wait_count == 3
    assert m.pacer_wait_s == 3.0
    assert m.terminal_failures == 1


# --- TokenBucket pacer: spaces submissions; a 0 rate is a pass-through ---


def test_pacer_spaces_submissions_at_configured_rate():
    t = [0.0]
    slept = []

    def clock():
        return t[0]

    def sleep(s):
        slept.append(s)
        t[0] += s                          # the fake clock advances by the sleep

    stats = ReliabilityStats()
    tb = TokenBucket(60, stats=stats, clock=clock, sleep=sleep)   # 60 rpm -> 1s gap
    assert tb.acquire() == 0.0             # first submission never waits
    wait = tb.acquire()                    # immediate second submission waits ~1s
    assert wait == pytest.approx(1.0)
    assert slept == [pytest.approx(1.0)]
    assert stats.pacer_wait_count == 1
    assert stats.pacer_wait_s == pytest.approx(1.0)


def test_pacer_disabled_when_rate_non_positive():
    slept = []
    tb = TokenBucket(0, clock=lambda: 0.0, sleep=lambda s: slept.append(s))
    for _ in range(5):
        assert tb.acquire() == 0.0
    assert slept == []


# --- call_with_retry: succeeds after transient failures, terminal on exhaustion ---


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    stats = ReliabilityStats()
    slept = []
    out = call_with_retry(
        fn, max_retries=5, backoff_base=2.0, backoff_cap=60.0, stats=stats,
        sleep=lambda s: slept.append(s), jitter=lambda lo, hi: hi,
    )
    assert out == "ok"
    assert calls["n"] == 3
    assert stats.total_retries == 2        # two retries before the third try won
    assert stats.terminal_failures == 0
    assert slept == [2.0, 4.0]             # exp backoff for attempts 0 and 1
    assert stats.max_backoff_s == 4.0
    assert stats.cumulative_wait_s == 6.0


def test_retry_terminal_reraises_after_exhaustion():
    def fn():
        raise RuntimeError("always")

    stats = ReliabilityStats()
    with pytest.raises(RuntimeError):
        call_with_retry(fn, max_retries=2, stats=stats,
                        sleep=lambda s: None, jitter=lambda lo, hi: 0.0)
    assert stats.terminal_failures == 1
    assert stats.total_retries == 2


def test_retry_backoff_stays_within_jitter_bounds():
    slept = []

    def fn():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):      # always fails -> terminal re-raise
        call_with_retry(fn, max_retries=3, backoff_base=2.0, backoff_cap=10.0,
                        sleep=lambda s: slept.append(s),
                        jitter=lambda lo, hi: (lo + hi) / 2,    # mid-point
                        stats=ReliabilityStats())
    caps = [2.0, 4.0, 8.0]                 # min(10, 2*2**n) for n = 0,1,2
    assert len(slept) == 3
    for s, cap in zip(slept, caps, strict=True):
        assert 0.0 <= s <= cap


def test_retry_honors_retry_after_as_a_floor():
    slept = []

    def fn():
        raise RuntimeError("HTTP 429 retry-after: 30")

    def retry_after_of(exc):
        return parse_retry_after(str(exc))

    with pytest.raises(RuntimeError):      # always fails -> terminal re-raise
        call_with_retry(fn, max_retries=1, backoff_base=2.0, backoff_cap=60.0,
                        retry_after_of=retry_after_of,
                        sleep=lambda s: slept.append(s),
                        jitter=lambda lo, hi: 0.0,         # backoff would be 0
                        stats=ReliabilityStats())
    assert slept == [30.0]                 # retry-after beats the 0 jittered backoff


# --- call_with_retry: a value-signalled failure (CallResult-style), no exception ---


def test_retry_value_failure_then_success_returns_value():
    seq = iter([("fail", True), ("fail", True), ("ok", False)])
    out = call_with_retry(lambda: next(seq), max_retries=5,
                          is_failure=lambda v: v[1],
                          sleep=lambda s: None, jitter=lambda lo, hi: 0.0,
                          stats=ReliabilityStats())
    assert out == ("ok", False)


def test_retry_value_failure_terminal_returns_last_value_not_raise():
    stats = ReliabilityStats()
    out = call_with_retry(lambda: ("fail", True), max_retries=2,
                          is_failure=lambda v: v[1],
                          sleep=lambda s: None, jitter=lambda lo, hi: 0.0, stats=stats)
    assert out == ("fail", True)           # terminal returns the last failed value
    assert stats.terminal_failures == 1
    assert stats.total_retries == 2


# --- per-call vs per-task wall-clock act independently ---


def test_task_timeout_caps_retries_independent_of_max_retries():
    # Each attempt "costs" 100 fake seconds of per-call wall-clock; a 250s task
    # budget must terminate after ~3 attempts even though max_retries is huge.
    t = [0.0]

    def clock():
        return t[0]

    def fn():
        t[0] += 100.0                      # per-call cost
        raise RuntimeError("per-call timeout")

    stats = ReliabilityStats()
    with pytest.raises(RuntimeError):
        call_with_retry(fn, max_retries=100, task_timeout=250.0,
                        backoff_base=0.0, backoff_cap=0.0, clock=clock,
                        sleep=lambda s: t.__setitem__(0, t[0] + s),
                        jitter=lambda lo, hi: 0.0, stats=stats)
    assert stats.terminal_failures == 1
    assert stats.total_retries == 2        # a0,a1 retried; a2 exceeds 250 -> terminal


def test_pacer_acquire_called_before_each_attempt():
    acquired = {"n": 0}

    class _Counter:
        def acquire(self):
            acquired["n"] += 1
            return 0.0

    def fn():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        call_with_retry(fn, max_retries=2, pacer=_Counter(),
                        sleep=lambda s: None, jitter=lambda lo, hi: 0.0,
                        stats=ReliabilityStats())
    assert acquired["n"] == 3              # initial attempt + 2 retries


# --- parse_retry_after: best-effort hint scan ---


def test_parse_retry_after_variants():
    assert parse_retry_after("Error 429: retry-after: 12") == 12.0
    assert parse_retry_after('{"retry-after": 5}') == 5.0
    assert parse_retry_after("Retry After 7s") == 7.0
    assert parse_retry_after("no hint here") is None
    assert parse_retry_after("") is None
    assert parse_retry_after(None) is None
