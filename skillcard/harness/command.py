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
    print(f"eval: {name} -- triggering ({args.workers}w x {args.runs_per_query} runs)...")
    trig_out = run_eval(
        load_eval_set(trig_path), name, description,
        num_workers=args.workers, timeout=args.timeout,
        runs_per_query=args.runs_per_query, model=args.model,
        workspace_base=args.workspace_base,
    )
    s = trig_out["summary"]
    print(f"  precision={s['precision']:.3f} recall={s['recall']} near_miss={s['specificity']}")

    func_out = None
    if not args.skip_functional:
        print("eval: functional (full workflow + grade per task)...")
        func_out = run_functional(skill_dir, model=args.model, timeout=max(args.timeout, 300))

    out_dir = Path(args.out) if args.out else skill_dir / "evals"
    today = datetime.date.today().isoformat()
    path = assemble.write_evals_json(
        skill_dir, out_dir, name, trig_out, func_out, args.model, today
    )
    tail = "results block populated" if func_out else "no results block: functional skipped -> beta"
    print(f"OK: wrote {path} ({tail})")
    return 0
