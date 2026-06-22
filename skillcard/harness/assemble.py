"""Assemble the generator-compatible ``evals.json`` results block (SPEC.md D).

The wrapper's join point: the trigger summary + the functional aggregate become
the ``results`` block that :func:`skillcard.discover._metrics` consumes. Two
invariants are enforced here:

* **specificity -> near_miss_precision.** The trigger harness emits
  ``specificity``; ``discover`` reads ``near_miss_precision``. Rename on the way
  in, or the metric is silently dropped (it is optional in the schema).
* **both-blocks-or-none.** ``schema.Metrics`` makes ``eval_pass_rate`` and
  ``task_completion_rate`` REQUIRED, and ``discover`` builds a metrics dict
  whenever ``results`` is truthy. A triggering-only block would crash
  ``build_card``, so a run without functional results writes NO ``results``
  block (the beta path).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skillcard.harness.provenance import harness_provenance


def _round(value: Any, ndigits: int = 4) -> Any:
    return round(value, ndigits) if isinstance(value, (int, float)) else value


def build_results_block(
    trig_out: dict,
    func_out: dict | None,
    model: str,
    date: str,
    best_of: int = 1,
    reliability: dict | None = None,
) -> dict | None:
    """Map a harness run (+ functional aggregate) to a ``results`` block, or None.

    ``best_of`` (default 1, single-shot) is recorded in the ``harness`` provenance
    string when > 1 (e.g. ``... / best_of_3``), so a populated cert states how the
    functional number was obtained. ``reliability`` (the merged rate-limit-resilience
    stats for the run) is recorded under ``reliability`` when given, so a
    throttled-but-recovered run is visible; omitted -> the v0.6.x block is unchanged.
    ``evals.json`` is excluded from ``content_hash``, so this provenance never moves
    the code identity.
    """
    s = trig_out["summary"]
    triggering = {
        "precision": _round(s["precision"]),
        "recall": _round(s["recall"]),
        # The rename: harness `specificity` is discover's `near_miss_precision`.
        "near_miss_precision": _round(s["specificity"]),
    }
    if func_out is None:
        # both-blocks-or-none: no functional metrics -> no results block (beta).
        return None
    functional = {
        "eval_pass_rate": _round(func_out["eval_pass_rate"]),
        "task_completion_rate": _round(func_out["task_completion_rate"]),
    }
    sampling = f"best_of_{best_of}" if best_of and best_of > 1 else None
    block = {
        "triggering": triggering,
        "functional": functional,
        "harness": harness_provenance(model, date, sampling=sampling),
        "date": date,
    }
    if reliability is not None:
        block["reliability"] = reliability
    return block


def write_evals_json(
    skill_dir: str | Path,
    out_dir: str | Path,
    skill_name: str,
    trig_out: dict,
    func_out: dict | None,
    model: str,
    date: str,
    best_of: int = 1,
    reliability: dict | None = None,
) -> Path:
    """Write ``<out_dir>/evals.json``: preserve existing ``evals[]``, recompute results.

    Only the ``results`` block is (re)computed; any committed ``evals[]`` task
    definitions and ``skill_name`` are carried through verbatim so authoring is
    not clobbered. When functional results are absent, no ``results`` key is
    written (the generator then treats the skill as beta).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"skill_name": skill_name}

    existing = Path(skill_dir) / "evals" / "evals.json"
    if existing.exists():
        prior = json.loads(existing.read_text(encoding="utf-8"))
        payload["skill_name"] = prior.get("skill_name", skill_name)
        if prior.get("evals") is not None:
            payload["evals"] = prior["evals"]

    block = build_results_block(
        trig_out, func_out, model, date, best_of=best_of, reliability=reliability
    )
    if block is not None:
        payload["results"] = block

    path = out_dir / "evals.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
