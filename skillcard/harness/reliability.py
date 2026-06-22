"""Rate-limit resilience for the metrics harness (SPEC.md section D, v0.7.0).

The harness drives the model by spawning the ``claude`` CLI as a child process, so
there is no in-process SDK whose retry/backoff/retry-after we can configure -- the
CLI runs its own client inside the subprocess. The only seam we own is the
subprocess boundary, and this module adds the two layers it lacks:

* :class:`TokenBucket` -- a proactive, per-run client-side pacer that spaces call
  submissions to stay under the account's per-minute window. This is the primary
  defense against sustained saturation: prevent the bursts rather than recover from
  them.
* :func:`call_with_retry` -- wraps a single attempt with exponential backoff and
  jitter, retrying a transient failure until either it succeeds, the retry budget is
  spent, or the per-task wall-clock budget is exhausted. A call that succeeds on a
  retry is a success; only a call whose retries are all spent is a TERMINAL failure.

:class:`ReliabilityStats` accumulates what happened (retries, waits, terminal
failures) so a throttled-but-recovered run is visible in the run provenance rather
than silent. ``clock``, ``sleep`` and ``jitter`` are all injectable so the logic is
exercised offline with no real waits; jitter only ever shapes a sleep duration and
never a sample choice, so eval sampling stays deterministic.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

# A retry-after hint anywhere in the CLI's error text. Best-effort: the header
# lives inside the child process, so it is usually absent and backoff governs.
_RETRY_AFTER_RE = re.compile(
    r"retry[-\s]?after[\"']?\s*[:=]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)


@dataclass
class ReliabilityStats:
    """Per-run accumulator of what the resilience layer did, for provenance.

    A run with ``total_retries > 0`` and ``terminal_failures == 0`` was throttled
    but recovered -- exactly the case the v0.6.2 collapse guard must NOT abort on.
    """

    total_retries: int = 0
    cumulative_wait_s: float = 0.0
    max_backoff_s: float = 0.0
    pacer_wait_count: int = 0
    pacer_wait_s: float = 0.0
    terminal_failures: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dict with the float fields rounded for output."""
        d = asdict(self)
        for k in ("cumulative_wait_s", "max_backoff_s", "pacer_wait_s"):
            d[k] = round(d[k], 3)
        return d

    def merge(self, other: ReliabilityStats) -> ReliabilityStats:
        """Combine two runs' stats: counts/waits sum, ``max_backoff_s`` is the max."""
        return ReliabilityStats(
            total_retries=self.total_retries + other.total_retries,
            cumulative_wait_s=self.cumulative_wait_s + other.cumulative_wait_s,
            max_backoff_s=max(self.max_backoff_s, other.max_backoff_s),
            pacer_wait_count=self.pacer_wait_count + other.pacer_wait_count,
            pacer_wait_s=self.pacer_wait_s + other.pacer_wait_s,
            terminal_failures=self.terminal_failures + other.terminal_failures,
        )


class TokenBucket:
    """Per-run pacer: ``acquire()`` blocks to keep submissions under ``rate`` rpm.

    A simple monotonic spacer -- consecutive submissions are held at least
    ``60 / rate`` seconds apart -- which is what a single serial run needs (and what
    the functional and default trigger paths are). ``rate <= 0`` makes ``acquire()``
    a no-op pass-through, so pacing is fully opt-out. ``clock``/``sleep`` are
    injectable for offline tests.
    """

    def __init__(
        self,
        rate: float,
        stats: ReliabilityStats | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate = rate
        self.min_interval = 60.0 / rate if rate and rate > 0 else 0.0
        self.stats = stats
        self._clock = clock
        self._sleep = sleep
        self._next_at: float | None = None

    def acquire(self) -> float:
        """Block until the next submission may go; return the seconds waited."""
        if self.min_interval <= 0:
            return 0.0
        now = self._clock()
        if self._next_at is None or now >= self._next_at:
            self._next_at = now + self.min_interval
            return 0.0
        wait = self._next_at - now
        self._sleep(wait)
        self._next_at += self.min_interval
        if self.stats is not None:
            self.stats.pacer_wait_count += 1
            self.stats.pacer_wait_s += wait
        return wait


def parse_retry_after(text: str | None) -> float | None:
    """Best-effort: pull a retry-after seconds value out of CLI output, else None."""
    if not text:
        return None
    m = _RETRY_AFTER_RE.search(text)
    return float(m.group(1)) if m else None


def _backoff(
    attempt: int,
    base: float,
    cap: float,
    retry_after: float | None,
    jitter: Callable[[float, float], float],
) -> float:
    """Full-jitter exponential backoff for ``attempt``; retry-after is a floor."""
    computed = min(cap, base * (2 ** attempt))
    wait = jitter(0.0, computed)
    if retry_after is not None:
        wait = max(wait, retry_after)
    return wait


def _hint(retry_after_of: Callable[[Any], float | None] | None, obj: Any) -> float | None:
    if retry_after_of is None:
        return None
    try:
        return retry_after_of(obj)
    except Exception:  # noqa: BLE001 -- a hint parser must never break the retry loop
        return None


def call_with_retry(
    fn: Callable[[], Any],
    *,
    max_retries: int = 0,
    backoff_base: float = 2.0,
    backoff_cap: float = 60.0,
    task_timeout: float | None = None,
    pacer: TokenBucket | None = None,
    stats: ReliabilityStats | None = None,
    is_failure: Callable[[Any], bool] | None = None,
    retry_after_of: Callable[[Any], float | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    jitter: Callable[[float, float], float] = random.uniform,
) -> Any:
    """Run ``fn()`` (one attempt) with pacing + retry; return its successful value.

    A retryable outcome is either an exception raised by ``fn`` OR a returned value
    for which ``is_failure(value)`` is true (so a primitive that signals failure by
    return -- e.g. a ``CallResult(failed=True)`` -- retries without raising). On a
    retryable outcome, if attempts remain AND the per-task wall-clock budget
    (``task_timeout``) is not yet spent, sleep a full-jitter exponential backoff
    (honoring a parseable retry-after as a floor) and try again.

    Defaults are a no-op: ``max_retries=0`` runs ``fn`` exactly once, so callers that
    do not opt in behave precisely as before. ``stats`` records retries / waits and,
    on a terminal outcome (retries or the task budget spent), ``terminal_failures``.
    The terminal outcome re-raises the last exception, or returns the last failed
    value when failure was signalled by return.
    """
    start = clock()
    attempt = 0
    last_exc: BaseException | None = None
    last_val: Any = None
    have_val = False

    while True:
        if pacer is not None:
            pacer.acquire()
        try:
            val = fn()
        except Exception as exc:  # noqa: BLE001 -- any attempt error is retryable
            last_exc, have_val = exc, False
            retry_after = _hint(retry_after_of, exc)
        else:
            if is_failure is not None and is_failure(val):
                last_val, have_val, last_exc = val, True, None
                retry_after = _hint(retry_after_of, val)
            else:
                return val  # success

        if attempt >= max_retries:
            break  # retries exhausted -> terminal
        elapsed = clock() - start
        if task_timeout is not None and elapsed >= task_timeout:
            break  # per-task wall-clock spent -> terminal
        wait = _backoff(attempt, backoff_base, backoff_cap, retry_after, jitter)
        if task_timeout is not None:
            wait = min(wait, task_timeout - elapsed)
        sleep(wait)
        if stats is not None:
            stats.total_retries += 1
            stats.cumulative_wait_s += wait
            stats.max_backoff_s = max(stats.max_backoff_s, wait)
        attempt += 1

    if stats is not None:
        stats.terminal_failures += 1
    if have_val:
        return last_val
    raise last_exc  # type: ignore[misc]
