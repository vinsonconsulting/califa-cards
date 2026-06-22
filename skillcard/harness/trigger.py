"""Trigger evaluation harness (namespace-isolated) -- SPEC.md section D.

Measures whether a skill's *description* causes Claude to trigger (invoke the
skill) for a set of queries, and computes precision / recall / specificity.

PORTED from the cabinet's ``tooling/skill-eval/run_eval.py`` (itself a fork of
skill-creator's ``scripts/run_eval.py``), at fork commit ``ef6f952`` -- see
:data:`FORK_SHA` and SPEC section D. The fork fixes a measurement bug in the upstream
harness: under parallel workers, every run wrote its per-run, uuid-named proxy
command into the SAME shared ``project_root/.claude/commands`` and ran
``claude -p`` there, so look-alike proxies coexisted and the model frequently
invoked a SIBLING run's proxy. The own-uuid exact-match scoring then counted
that a miss -> systematic false-low recall that worsens with worker count (the
github-readme 0.139 artifact).

Two changes fix it, ported verbatim:
  1. Namespace isolation (the source fix): each run gets its OWN working dir under
     ``~/.cache/skill-eval-workspaces/<uuid>/`` containing only its own proxy, and
     ``claude -p`` runs there (``cwd=workdir``). Sibling proxies are never on a
     worker's path.
  2. Identity-match scoring (defense in depth): a hit is any first-tool invocation
     of a proxy for the skill-under-test (prefix ``<skill>-skill-``).

The only adaptation for califa: ``parse_skill_md`` reuses califa's frontmatter
parser instead of skill-creator's hand-rolled one.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

from skillcard.harness.reliability import ReliabilityStats, TokenBucket, call_with_retry

# Short SHA of the cabinet fork commit this runner was ported from (provenance).
FORK_SHA = "ef6f952"

# Per-run isolated workspaces live UNDER ~/ (never /tmp), per the harness's
# workspace convention. Each run gets its own <uuid>/ subdir; we remove it after.
EVAL_WORKSPACE_ROOT = Path.home() / ".cache" / "skill-eval-workspaces"


class CallResult(NamedTuple):
    """Outcome of one ``claude -p`` eval call.

    ``triggered`` is the trigger decision; ``failed`` marks an INFRASTRUCTURE
    failure (429 / rate-limit / network error / timeout / spawn error) as opposed
    to a call that completed and simply did not trigger. The collapse guard keys
    on ``failed`` -- never on a low score -- so a saturated run refuses while a
    weak-but-honest skill still records.
    """

    triggered: bool
    failed: bool


class EvalIntegrityError(RuntimeError):
    """Raised when too many eval calls FAILED to record a trustworthy measurement.

    A rate-limited / errored / timed-out call produces no trigger and, counted as
    a miss, drives false-low metrics. When the call-failure rate crosses
    :data:`CALL_FAILURE_ABORT_THRESHOLD` the runner raises this instead of emitting
    the floor, so nothing is written.
    """


# A run whose eval calls fail at or above this rate is rate-limit / error
# saturation, not a measurement: a healthy run fails ~0 calls, so 0.2 leaves wide
# margin yet catches the bursts (typically well above half) behind the floor
# artifacts. A module constant -- tunable, not a CLI flag.
CALL_FAILURE_ABORT_THRESHOLD = 0.2


def guard_call_failures(total: int, failed: int, threshold: float, context: str) -> None:
    """Raise :class:`EvalIntegrityError` when the call-failure rate is too high.

    No-op when no calls ran (``total <= 0``) or the rate is below ``threshold``.
    Keyed on call FAILURES (infrastructure), so a run whose calls all succeed --
    even at a low score -- never trips this.
    """
    if total <= 0:
        return
    if failed / total >= threshold:
        raise EvalIntegrityError(
            f"{failed} of {total} {context} calls failed (rate-limit / errors) -- "
            f"not a valid measurement; reduce load or retry later (ensure --workers 1)."
        )


def parse_skill_md(skill_path: str | Path) -> tuple[str, str, str]:
    """Return ``(name, description, full_content)`` for a skill dir's SKILL.md.

    Reuses califa's :func:`skillcard.cli.parse_frontmatter` (a real YAML parse,
    so block scalars are handled correctly) and collapses a folded description to
    one line -- the same normalization :func:`skillcard.discover._scalar` applies,
    so the measured text is exactly what the generated card will carry.
    """
    from skillcard.cli import parse_frontmatter  # noqa: PLC0415

    skill_path = Path(skill_path)
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    name = str(fm.get("name") or "")
    description = fm.get("description") or ""
    if isinstance(description, str):
        description = " ".join(description.split())
    return name, description, content


def claude_env() -> dict[str, str]:
    """Environment for a nested ``claude -p`` call.

    Drops ``CLAUDECODE`` so ``claude -p`` may nest inside a Claude Code session;
    the guard is for interactive terminal conflicts, programmatic subprocess use
    is safe. Shared with the functional orchestrator.
    """
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}


def make_isolated_workspace(
    skill_name: str,
    skill_description: str,
    base: Path | None = None,
) -> tuple[Path, Path, str]:
    """Create a per-run isolated workspace and write this run's proxy command.

    Returns ``(workdir, proxy_path, clean_name)``. ``workdir`` is a fresh
    ``base/<uuid>`` dir containing only ``.claude/commands/<clean_name>.md`` -- so
    a ``claude -p`` run with ``cwd=workdir`` sees exactly ONE skill proxy (this
    run's) and can never invoke a sibling run's look-alike proxy. This is the
    source fix for the parallel namespace-contamination bug.
    """
    base = base if base is not None else EVAL_WORKSPACE_ROOT
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    workdir = base / unique_id
    commands_dir = workdir / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = commands_dir / f"{clean_name}.md"

    # Use a YAML block scalar so quotes in the description can't break frontmatter.
    indented_desc = "\n  ".join(skill_description.split("\n"))
    proxy_path.write_text(
        f"---\n"
        f"description: |\n"
        f"  {indented_desc}\n"
        f"---\n\n"
        f"# {skill_name}\n\n"
        f"This skill handles: {skill_description}\n"
    )
    return workdir, proxy_path, clean_name


def is_trigger(tool_name: str, name_field: str, skill_name: str) -> bool:
    """Return True if a first tool call counts as triggering the skill-under-test.

    Counts a hit when the invoked Skill name / Read file_path references ANY proxy
    for this skill (prefix ``<skill_name>-skill-``), which subsumes the run's own
    uuid'd proxy. Exact for single-skill runs (the only proxy that can match is one
    of this skill's). Keep one skill per eval set when relying on this predicate.
    """
    if tool_name not in ("Skill", "Read"):
        return False
    return f"{skill_name}-skill-" in name_field


def load_eval_set(path: str | Path) -> list[dict]:
    """Load an eval set from JSON (array) or JSONL (one object per line).

    The repo standardizes on ``triggering.jsonl`` (JSON Lines). Detect by
    extension, with a content fallback so a ``.json`` file containing JSONL still
    parses, and tolerate the ``{"evals": [...]}`` wrapper.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        return data.get("evals", [data])
    return data


class _StreamDecider:
    """Incrementally parse ``claude -p`` stream-json lines into a trigger decision.

    ``feed(buffer)`` consumes the complete lines in ``buffer`` and returns
    ``(decision, remaining)``: ``decision`` is ``True``/``False`` once a decisive
    event is seen (a first tool choice, ``message_stop``, the terminal ``result``)
    and ``None`` while more data is needed. Pending-tool state carries across feeds,
    so a decision split over chunks -- or arriving only in the final post-exit tail
    (the poll-break path) -- is still detected rather than mis-scored as a miss.
    """

    def __init__(self, skill_name: str) -> None:
        self.skill_name = skill_name
        self.pending_tool_name: str | None = None
        self.accumulated_json = ""

    def feed(self, buffer: str) -> tuple[bool | None, str]:
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            decision = self._handle(event)
            if decision is not None:
                return decision, buffer
        return None, buffer

    def _handle(self, event: dict) -> bool | None:
        etype = event.get("type")
        if etype == "stream_event":
            se = event.get("event", {})
            se_type = se.get("type", "")
            if se_type == "content_block_start":
                cb = se.get("content_block", {})
                if cb.get("type") == "tool_use":
                    tool_name = cb.get("name", "")
                    if tool_name in ("Skill", "Read"):
                        self.pending_tool_name = tool_name
                        self.accumulated_json = ""
                    else:
                        return False
            elif se_type == "content_block_delta" and self.pending_tool_name:
                delta = se.get("delta", {})
                if delta.get("type") == "input_json_delta":
                    self.accumulated_json += delta.get("partial_json", "")
                    if is_trigger(self.pending_tool_name, self.accumulated_json, self.skill_name):
                        return True
            elif se_type in ("content_block_stop", "message_stop"):
                if self.pending_tool_name:
                    return is_trigger(
                        self.pending_tool_name, self.accumulated_json, self.skill_name
                    )
                if se_type == "message_stop":
                    return False
        elif etype == "assistant":
            message = event.get("message", {})
            for content_item in message.get("content", []):
                if content_item.get("type") != "tool_use":
                    continue
                tool_name = content_item.get("name", "")
                tool_input = content_item.get("input", {})
                field = (
                    tool_input.get("skill", "")
                    if tool_name == "Skill"
                    else tool_input.get("file_path", "")
                )
                return is_trigger(tool_name, field, self.skill_name)
        elif etype == "result":
            # Terminal success event with no earlier tool choice: ran, didn't trigger.
            return False
        return None


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    model: str | None = None,
    workspace_base: str | None = None,
) -> CallResult:
    """Run a single query; return a :class:`CallResult` (triggered / failed).

    Creates an ISOLATED workspace (only this run's proxy is visible), runs
    ``claude -p`` with the raw query there, and detects triggering early from
    stream events via :class:`_StreamDecider`. A run that ends with no decisive
    event parsed (timeout / killed / errored ``claude -p``) is an INFRASTRUCTURE
    failure (``failed=True``), distinct from a completed call that did not trigger.
    """
    base = Path(workspace_base) if workspace_base else None
    workdir, _proxy_path, _clean_name = make_isolated_workspace(
        skill_name, skill_description, base=base
    )

    try:
        cmd = [
            "claude",
            "-p", query,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if model:
            cmd.extend(["--model", model])

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(workdir),
            env=claude_env(),
        )

        decider = _StreamDecider(skill_name)
        start_time = time.time()
        buffer = ""

        try:
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        buffer += remaining.decode("utf-8", errors="replace")
                    decision, buffer = decider.feed(buffer)
                    if decision is not None:
                        return CallResult(triggered=decision, failed=False)
                    break

                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    continue

                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    decision, buffer = decider.feed(buffer)
                    if decision is not None:
                        return CallResult(triggered=decision, failed=False)
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                decision, buffer = decider.feed(buffer)
                if decision is not None:
                    return CallResult(triggered=decision, failed=False)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        # No decisive event parsed -> the call was cut short (timeout / kill /
        # error): an infrastructure FAILURE, not a clean miss.
        return CallResult(triggered=False, failed=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _metrics(results: list[dict]) -> dict:
    """Compute precision/recall/specificity over per-query trigger counts.

    recall = triggers on positives / positive runs (mirrors run_loop's formula).
    precision = TP / (TP + FP). specificity = TN / negative runs -- the harness's
    name for the card's ``near_miss_precision`` (fraction of sibling near-misses
    that did NOT false-trigger). The wrapper renames it on assembly.
    """
    pos = [r for r in results if r["should_trigger"]]
    neg = [r for r in results if not r["should_trigger"]]
    tp = sum(r["triggers"] for r in pos)
    pos_runs = sum(r["runs"] for r in pos)
    fn = pos_runs - tp
    fp = sum(r["triggers"] for r in neg)
    neg_runs = sum(r["runs"] for r in neg)
    tn = neg_runs - fp
    return {
        "precision": tp / (tp + fp) if (tp + fp) > 0 else 1.0,
        "recall": tp / pos_runs if pos_runs > 0 else None,
        "specificity": tn / neg_runs if neg_runs > 0 else None,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "positive_runs": pos_runs, "negative_runs": neg_runs,
    }


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
    workspace_base: str | None = None,
    query_fn=None,
    failure_threshold: float = CALL_FAILURE_ABORT_THRESHOLD,
    max_retries: int = 0,
    backoff_base: float = 2.0,
    backoff_cap: float = 60.0,
    task_timeout: float | None = None,
    rate_limit: float = 0,
    sleep=time.sleep,
) -> dict:
    """Run the full eval set and return per-query results + summary.

    Serial by default (``num_workers <= 1``): each call runs in-process, which is
    reliable and the injectable seam for tests. ``num_workers > 1`` opts into the
    ProcessPoolExecutor fan-out, faster but able to saturate the account's rate
    limit when nested in a session. ``query_fn`` (default :func:`run_single_query`)
    is resolved at call time so tests can monkeypatch it.

    Call FAILURES (429 / timeout / errored ``claude -p``) are tracked apart from
    completed-but-no-trigger calls and excluded from the per-query denominators (a
    failed call is not evidence the description failed to fire). A failure is only
    counted once its retries are spent: on the SERIAL path each call goes through
    :func:`call_with_retry` with a :class:`TokenBucket` pacer, so a throttled call
    that recovers on retry records as a success and a TERMINAL failure is what feeds
    the guard. ``timeout`` bounds one attempt; ``task_timeout`` bounds all retries of
    one call. The retry/pace knobs default to a no-op (``max_retries=0``,
    ``rate_limit=0``); the parallel branch stays single-attempt. If the terminal
    call-failure rate reaches ``failure_threshold`` the run is refused via
    :func:`guard_call_failures` -- it raises and nothing downstream is written. The
    accumulated :class:`ReliabilityStats` is surfaced under ``summary.reliability``.
    """
    qf = query_fn or run_single_query
    stats = ReliabilityStats()
    pacer = TokenBucket(rate_limit, stats=stats, sleep=sleep)
    call_specs = [item for item in eval_set for _ in range(runs_per_query)]

    query_outcomes: dict[str, list[CallResult]] = {}
    query_items: dict[str, dict] = {}

    def record(item: dict, outcome: CallResult) -> None:
        query = item["query"]
        query_items[query] = item
        query_outcomes.setdefault(query, []).append(outcome)

    if num_workers and num_workers > 1:
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_to_item = {
                executor.submit(
                    qf, item["query"], skill_name, description,
                    timeout, model, workspace_base,
                ): item
                for item in call_specs
            }
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    outcome = future.result()
                except Exception as e:  # noqa: BLE001
                    print(f"Warning: query call failed: {e}", file=sys.stderr)
                    outcome = CallResult(triggered=False, failed=True)
                record(item, outcome)
    else:
        for item in call_specs:
            try:
                outcome = call_with_retry(
                    lambda it=item: qf(
                        it["query"], skill_name, description,
                        timeout, model, workspace_base,
                    ),
                    max_retries=max_retries, backoff_base=backoff_base,
                    backoff_cap=backoff_cap, task_timeout=task_timeout,
                    pacer=pacer, stats=stats,
                    is_failure=lambda r: r.failed, sleep=sleep,
                )
            except Exception as e:  # noqa: BLE001
                # Every retry raised: a terminal infrastructure failure (already
                # counted in ``stats`` by call_with_retry).
                print(f"Warning: query call failed: {e}", file=sys.stderr)
                outcome = CallResult(triggered=False, failed=True)
            record(item, outcome)

    calls_total = sum(len(outcomes) for outcomes in query_outcomes.values())
    calls_failed = sum(
        1 for outcomes in query_outcomes.values() for o in outcomes if o.failed
    )
    guard_call_failures(calls_total, calls_failed, failure_threshold, "trigger eval")

    results = []
    for query, outcomes in query_outcomes.items():
        item = query_items[query]
        successful = [o for o in outcomes if not o.failed]
        triggers = sum(1 for o in successful if o.triggered)
        runs = len(successful)
        trigger_rate = triggers / runs if runs else 0.0
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": triggers,
            "runs": runs,
            "pass": did_pass,
        })

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    metrics = _metrics(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "calls_total": calls_total,
            "calls_failed": calls_failed,
            "reliability": stats.as_dict(),
            **metrics,
        },
    }
