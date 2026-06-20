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

# Short SHA of the cabinet fork commit this runner was ported from (provenance).
FORK_SHA = "ef6f952"

# Per-run isolated workspaces live UNDER ~/ (never /tmp), per the harness's
# workspace convention. Each run gets its own <uuid>/ subdir; we remove it after.
EVAL_WORKSPACE_ROOT = Path.home() / ".cache" / "skill-eval-workspaces"


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


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    model: str | None = None,
    workspace_base: str | None = None,
) -> bool:
    """Run a single query and return whether the skill was triggered.

    Creates an ISOLATED workspace (only this run's proxy is visible), runs
    ``claude -p`` with the raw query in that workspace, and detects triggering
    early from stream events (``content_block_start``) so we don't wait for the
    full assistant message, which only arrives after tool execution.
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

        triggered = False
        start_time = time.time()
        buffer = ""
        pending_tool_name = None
        accumulated_json = ""

        try:
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        buffer += remaining.decode("utf-8", errors="replace")
                    break

                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    continue

                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type") == "stream_event":
                        se = event.get("event", {})
                        se_type = se.get("type", "")

                        if se_type == "content_block_start":
                            cb = se.get("content_block", {})
                            if cb.get("type") == "tool_use":
                                tool_name = cb.get("name", "")
                                if tool_name in ("Skill", "Read"):
                                    pending_tool_name = tool_name
                                    accumulated_json = ""
                                else:
                                    return False

                        elif se_type == "content_block_delta" and pending_tool_name:
                            delta = se.get("delta", {})
                            if delta.get("type") == "input_json_delta":
                                accumulated_json += delta.get("partial_json", "")
                                if is_trigger(pending_tool_name, accumulated_json, skill_name):
                                    return True

                        elif se_type in ("content_block_stop", "message_stop"):
                            if pending_tool_name:
                                return is_trigger(pending_tool_name, accumulated_json, skill_name)
                            if se_type == "message_stop":
                                return False

                    elif event.get("type") == "assistant":
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
                            return is_trigger(tool_name, field, skill_name)

                    elif event.get("type") == "result":
                        return triggered
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        return triggered
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
) -> dict:
    """Run the full eval set (parallel) and return per-query results + summary."""
    results = []

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info = {}
        for item in eval_set:
            for run_idx in range(runs_per_query):
                future = executor.submit(
                    run_single_query,
                    item["query"],
                    skill_name,
                    description,
                    timeout,
                    model,
                    workspace_base,
                )
                future_to_info[future] = (item, run_idx)

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict] = {}
        for future in as_completed(future_to_info):
            item, _ = future_to_info[future]
            query = item["query"]
            query_items[query] = item
            if query not in query_triggers:
                query_triggers[query] = []
            try:
                query_triggers[query].append(future.result())
            except Exception as e:  # noqa: BLE001
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[query].append(False)

    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        if should_trigger:
            did_pass = trigger_rate >= trigger_threshold
        else:
            did_pass = trigger_rate < trigger_threshold
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": trigger_rate,
            "triggers": sum(triggers),
            "runs": len(triggers),
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
            **metrics,
        },
    }
