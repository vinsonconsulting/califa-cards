"""The ``skillcard eval`` command body (SPEC.md section D).

Lives in the harness package -- not in ``cli.py`` -- so the ``subprocess`` and
``claude``-driving surface stays out of the gated self-scan (the harness is
excluded from ``make scan`` as framework tooling). ``cli.py`` only declares the
subparser and delegates here.
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
from pathlib import Path

from skillcard.harness import assemble, run_eval, run_functional
from skillcard.harness.trigger import load_eval_set, parse_skill_md


def _skill_md_is_dirty(skill_dir: Path) -> bool:
    """True if SKILL.md has uncommitted changes (a working-tree draft, not committed)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(skill_dir), "diff", "--quiet", "--", "SKILL.md"],
            capture_output=True,
        )
        # git diff --quiet: 0 = no diff, 1 = differences, other = not a repo / error.
        return r.returncode == 1
    except (FileNotFoundError, OSError):
        return False


def _merge_reliability(*blocks: dict | None) -> dict:
    """Combine per-phase reliability stat dicts: counts/waits sum, backoff is maxed."""
    out = {"total_retries": 0, "cumulative_wait_s": 0.0, "max_backoff_s": 0.0,
           "pacer_wait_count": 0, "pacer_wait_s": 0.0, "terminal_failures": 0}
    for block in blocks:
        if not block:
            continue
        out["total_retries"] += block.get("total_retries", 0)
        out["cumulative_wait_s"] += block.get("cumulative_wait_s", 0.0)
        out["pacer_wait_count"] += block.get("pacer_wait_count", 0)
        out["pacer_wait_s"] += block.get("pacer_wait_s", 0.0)
        out["terminal_failures"] += block.get("terminal_failures", 0)
        out["max_backoff_s"] = max(out["max_backoff_s"], block.get("max_backoff_s", 0.0))
    return out


def run_eval_command(args) -> int:
    """Run the metrics harness (live ``claude -p``) and write evals/evals.json.

    Triggering via the namespace-isolated runner; functional via the skill's own
    graders. Refuses without the token-spend ack so an accidental call (or CI)
    never spends tokens. Writes both ``results`` sub-blocks or none (beta path).
    """
    if not args.ack:
        print("FAIL: `skillcard eval` makes live `claude -p` calls (spends tokens). "
              "Re-run with --i-understand-this-spends-tokens.")
        return 2
    best_of = getattr(args, "best_of", 1) or 1
    if best_of < 1:
        print(f"FAIL: --best-of must be >= 1 (got {best_of}).")
        return 2
    if shutil.which("claude") is None:
        print("FAIL: `claude` CLI not found on PATH; `skillcard eval` needs it for live runs.")
        return 1

    skill_dir = Path(args.skill_dir)
    trig_path = skill_dir / "evals" / "triggering.jsonl"
    if not trig_path.exists():
        print(f"FAIL: {skill_dir}: no evals/triggering.jsonl to evaluate")
        return 1

    # Sequencing guard: the harness measures SKILL.md's CURRENT description, so
    # warn if it is uncommitted (a working-tree draft, not the optimized text).
    if _skill_md_is_dirty(skill_dir):
        print("WARN: SKILL.md has uncommitted changes; measuring the working-tree "
              "description, not a committed one.")

    name, description, _ = parse_skill_md(skill_dir)
    # Rate-limit resilience knobs; getattr keeps older arg Namespaces (and tests)
    # working with the no-op defaults while the CLI supplies the real ones.
    max_retries = getattr(args, "max_retries", 0)
    task_timeout = getattr(args, "task_timeout", None)
    rate_limit = getattr(args, "rate_limit", 0)
    backoff_base = getattr(args, "backoff_base", 2.0)
    backoff_cap = getattr(args, "backoff_cap", 60.0)
    print(f"eval: {name} -- triggering ({args.workers}w x {args.runs_per_query} runs)...")
    trig_out = run_eval(
        load_eval_set(trig_path), name, description,
        num_workers=args.workers, timeout=args.timeout,
        runs_per_query=args.runs_per_query, model=args.model,
        workspace_base=args.workspace_base,
        max_retries=max_retries, backoff_base=backoff_base, backoff_cap=backoff_cap,
        task_timeout=task_timeout, rate_limit=rate_limit,
    )
    s = trig_out["summary"]
    print(f"  precision={s['precision']:.3f} recall={s['recall']} near_miss={s['specificity']}")

    func_out = None
    if not args.skip_functional:
        sampling = f" best-of-{best_of}" if best_of > 1 else ""
        print(f"eval: functional (full workflow + grade per task){sampling}...")
        func_out = run_functional(
            skill_dir, model=args.model, timeout=max(args.timeout, 300), best_of=best_of,
            max_retries=max_retries, backoff_base=backoff_base, backoff_cap=backoff_cap,
            task_timeout=task_timeout, rate_limit=rate_limit,
        )
        if func_out:
            print(f"  eval_pass_rate={func_out['eval_pass_rate']:.3f} "
                  f"task_completion={func_out['tasks_passed']}")
            for t in func_out.get("per_task", []):
                mark = "ok  " if t["passed"] == t["total"] else "MISS"
                print(f"    [{mark}] {t['id']}: {t['passed']}/{t['total']} "
                      f"(pass_rate={t['pass_rate']:.3f})")

    reliability = _merge_reliability(
        trig_out["summary"].get("reliability"),
        func_out.get("reliability") if func_out else None,
    )
    print(
        f"  reliability: retries={reliability['total_retries']} "
        f"wait={reliability['cumulative_wait_s']:.1f}s "
        f"max_backoff={reliability['max_backoff_s']:.1f}s "
        f"pacer_waits={reliability['pacer_wait_count']} "
        f"terminal_failures={reliability['terminal_failures']}"
    )

    out_dir = Path(args.out) if args.out else skill_dir / "evals"
    today = datetime.date.today().isoformat()
    path = assemble.write_evals_json(
        skill_dir, out_dir, name, trig_out, func_out, args.model, today,
        best_of=best_of, reliability=reliability,
    )
    tail = "results block populated" if func_out else "no results block: functional skipped -> beta"
    print(f"OK: wrote {path} ({tail})")
    return 0
