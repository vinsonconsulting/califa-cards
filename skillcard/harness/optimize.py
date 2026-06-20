"""``skillcard optimize`` -- description optimizer (SPEC.md section C).

Ports skill-creator's ``run_loop.py`` description optimizer into the harness,
reusing the namespace-isolated trigger runner
(:func:`skillcard.harness.trigger.run_eval`) for measurement. We do NOT shell out
to the installed ``run_loop.py``: it drives skill-creator's *un-forked* parallel
eval -- the shared ``.claude/commands`` uuid-proxy contamination bug the repo
forked away from (see :mod:`skillcard.harness.trigger`). Porting keeps both the
eval and the optimize paths on the isolated runner.

The loop measures the current description, asks ``claude -p`` to propose a better
one (generalising from trigger failures, not overfitting), re-measures, and keeps
the highest-scoring candidate. Optimising the description legitimately moves the
skill's ``content_hash`` (a real identity change), so the command never writes
silently: it surfaces a review diff and writes to SKILL.md ONLY on accept.

Lives in the harness package (excluded from ``make scan``) because it drives
``claude``; ``cli.py`` only declares the subparser and delegates here.
"""

from __future__ import annotations

import datetime
import difflib
import re
import shutil
import subprocess
import textwrap
from collections.abc import Callable
from pathlib import Path

from skillcard.harness.provenance import harness_provenance
from skillcard.harness.trigger import claude_env, load_eval_set, parse_skill_md, run_eval

_DESC_RE = re.compile(r"<new_description>(.*?)</new_description>", re.DOTALL)


def _call_claude(prompt: str, model: str | None, timeout: int = 300) -> str:
    """Run ``claude -p`` with the prompt on stdin; return the text response.

    The prompt goes over stdin (not argv) because it embeds the full SKILL.md body.
    Mirrors the trigger runner's auth/env handling via :func:`claude_env`.
    """
    cmd = ["claude", "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True,
        env=claude_env(), timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}\nstderr: {proc.stderr}")
    return proc.stdout


def _eval_set_from_skill(skill_dir: Path) -> list[dict]:
    """Build the trigger eval set for optimization.

    Prefer ``evals/triggering.jsonl``; else derive it from the inline ``triggers:``
    block in SKILL.md frontmatter. Deriving lets ``optimize`` run on any skill that
    declares triggers without a separate eval file (which would move content_hash).
    """
    from skillcard.cli import parse_frontmatter  # noqa: PLC0415

    trig = skill_dir / "evals" / "triggering.jsonl"
    if trig.exists():
        return load_eval_set(trig)
    fm = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    triggers = fm.get("triggers") or {}
    eval_set: list[dict] = []
    for should, key in ((True, "positive"), (False, "negative")):
        for q in triggers.get(key, []) or []:
            query = q if isinstance(q, str) else (q.get("prompt") or q.get("query") or "")
            if query:
                eval_set.append({"query": query, "should_trigger": should})
    return eval_set


def _propose_description(
    skill_name: str,
    content: str,
    current_description: str,
    eval_results: dict,
    history: list[dict],
    model: str | None,
) -> str:
    """Ask ``claude -p`` for an improved description from the trigger failures.

    Ported from skill-creator's ``improve_description.py`` (single-set variant):
    generalise from failures to broader user intent rather than overfitting to the
    specific queries, stay under the 1024-char hard limit, return one description.
    """
    results = eval_results["results"]
    failed = [r for r in results if r["should_trigger"] and not r["pass"]]
    false_pos = [r for r in results if not r["should_trigger"] and not r["pass"]]
    s = eval_results["summary"]

    prompt = (
        f'You are optimizing a skill description for a Claude Code skill called '
        f'"{skill_name}". A skill has a title and description Claude sees when '
        f'deciding whether to use it; if it does, it reads the full SKILL.md. The '
        f"description appears in Claude's available_skills list, and Claude decides "
        f'whether to invoke the skill based solely on the title and this description. '
        f'Your goal: trigger for relevant queries, and NOT for irrelevant ones.\n\n'
        f'Current description:\n<current_description>\n"{current_description}"\n'
        f'</current_description>\n\n'
        f'Current score: {s["passed"]}/{s["total"]} queries pass.\n\n'
    )
    if failed:
        prompt += "FAILED TO TRIGGER (should have, but did not):\n"
        for r in failed:
            prompt += f'  - "{r["query"]}" (triggered {r["triggers"]}/{r["runs"]})\n'
        prompt += "\n"
    if false_pos:
        prompt += "FALSE TRIGGERS (triggered but should not have):\n"
        for r in false_pos:
            prompt += f'  - "{r["query"]}" (triggered {r["triggers"]}/{r["runs"]})\n'
        prompt += "\n"
    if history:
        prompt += ("PREVIOUS ATTEMPTS (do NOT repeat -- try something structurally "
                   "different):\n")
        for h in history:
            prompt += f'  [{h.get("passed", 0)}/{h.get("total", 0)}] "{h["description"]}"\n'
        prompt += "\n"
    prompt += (
        f"Skill content (context on what it does):\n<skill_content>\n{content}\n"
        f"</skill_content>\n\n"
        "Write an improved description. Generalise from the failures to broader "
        "categories of user intent -- do NOT produce an ever-expanding list of "
        "specific queries (that overfits and wastes space, since the description is "
        "injected into every query). Keep it to about 100-200 words and comfortably "
        "under the 1024-character hard limit. Tips: phrase it imperatively (\"Use "
        "this skill for...\"); focus on the user's intent, not implementation; make "
        "it distinctive so it competes well for attention. Respond with ONLY the new "
        "description in <new_description> tags."
    )

    text = _call_claude(prompt, model)
    m = _DESC_RE.search(text)
    desc = (m.group(1) if m else text).strip().strip('"')
    if len(desc) > 1024:
        shorten = (
            f"{prompt}\n\n---\n\nA previous attempt produced this description, which "
            f"at {len(desc)} characters is over the 1024-character hard limit:\n\n"
            f'"{desc}"\n\nRewrite it under 1024 characters, keeping the most important '
            f"trigger words and intent coverage. Respond with ONLY the new description "
            f"in <new_description> tags."
        )
        text = _call_claude(shorten, model)
        m = _DESC_RE.search(text)
        desc = (m.group(1) if m else text).strip().strip('"')
    return " ".join(desc.split())


def _render_description_block(
    new_desc: str, indent: str = "  ", width: int = 88
) -> list[str]:
    """Render a description as a wrapped, indented YAML folded block scalar (``>-``)."""
    wrapped = textwrap.wrap(new_desc, width=max(width - len(indent), 20)) or [""]
    return ["description: >-"] + [f"{indent}{line}" for line in wrapped]


def _write_description(skill_dir: Path, new_desc: str) -> None:
    """Replace the top-level ``description:`` in SKILL.md frontmatter, in place.

    Format-preserving: only the description key (and any block-scalar continuation
    lines, up to the next top-level key or the closing ``---``) is rewritten; every
    other frontmatter field and the whole body are left untouched.
    """
    path = skill_dir / "SKILL.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: no YAML frontmatter to update")
    fm_end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if fm_end is None:
        raise ValueError(f"{path}: unterminated YAML frontmatter")
    start = next(
        (i for i in range(1, fm_end) if re.match(r"^description\s*:", lines[i])), None
    )
    if start is None:
        raise ValueError(f"{path}: no top-level 'description:' in frontmatter")
    # Extend through indented/blank continuation lines (a block scalar's body).
    end = start + 1
    while end < fm_end and (not lines[end].strip() or lines[end][:1] in (" ", "\t")):
        end += 1
    lines[start:end] = _render_description_block(new_desc)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_optimize(
    skill_dir: str | Path,
    model: str | None,
    *,
    workers: int = 4,
    timeout: int = 60,
    runs_per_query: int = 3,
    max_iterations: int = 3,
    workspace_base: str | None = None,
    measure: Callable[[str], dict] | None = None,
    propose: Callable[[str, dict, list], str] | None = None,
) -> dict:
    """Measure -> propose -> re-measure loop; return the best description + scores.

    ``measure(desc) -> run_eval-shaped dict`` and ``propose(desc, eval, history) ->
    str`` are injectable so tests run the loop with ZERO ``claude`` calls. Defaults
    use the isolated trigger runner and ``claude -p`` respectively.
    """
    skill_dir = Path(skill_dir)
    name, original, content = parse_skill_md(skill_dir)
    eval_set = _eval_set_from_skill(skill_dir)
    if not eval_set:
        raise ValueError(
            f"{skill_dir}: no eval set to optimize against (add evals/triggering.jsonl "
            f"or a triggers: block to SKILL.md)"
        )

    if measure is None:
        def measure(desc: str) -> dict:
            return run_eval(
                eval_set, name, desc, num_workers=workers, timeout=timeout,
                runs_per_query=runs_per_query, model=model, workspace_base=workspace_base,
            )
    if propose is None:
        def propose(desc: str, ev: dict, hist: list) -> str:
            return _propose_description(name, content, desc, ev, hist, model)

    history: list[dict] = []
    candidates: list[tuple[str, dict]] = []

    def record(desc: str, ev: dict) -> None:
        candidates.append((desc, ev))
        s = ev["summary"]
        history.append({"description": desc, "passed": s["passed"],
                        "total": s["total"], "results": ev["results"]})

    base_eval = measure(original)
    record(original, base_eval)
    for _ in range(max_iterations):
        cur_desc, cur_eval = candidates[-1]
        if cur_eval["summary"]["failed"] == 0:
            break  # already perfect; nothing to improve
        new_desc = propose(cur_desc, cur_eval, history[:-1])
        if not new_desc or new_desc == cur_desc:
            break
        record(new_desc, measure(new_desc))

    # Best = most passed, then fewest false positives; ties keep the earlier
    # candidate, so the original wins unless a proposal is strictly better.
    best = 0
    for i in range(1, len(candidates)):
        cs, bs = candidates[i][1]["summary"], candidates[best][1]["summary"]
        if (cs["passed"], -cs["fp"]) > (bs["passed"], -bs["fp"]):
            best = i
    best_desc, best_eval = candidates[best]

    date = datetime.date.today().isoformat()
    return {
        "skill_name": name,
        "original": original,
        "proposed": best_desc,
        "improved": best_desc != original,
        "before": base_eval["summary"],
        "after": best_eval["summary"],
        "iterations": len(candidates) - 1,
        "history": [{"description": h["description"], "passed": h["passed"],
                     "total": h["total"]} for h in history],
        "model": model,
        "date": date,
        "harness": harness_provenance(model, date),
    }


def _fmt(x: float | None) -> str:
    """Format a metric for the terminal: ``n/a`` for None, else 3 decimals."""
    return "n/a" if x is None else f"{x:.3f}"


def run_optimize_command(args) -> int:
    """The ``skillcard optimize`` command body: optimize, review-diff, write on accept.

    Refuses without the token-spend ack. Proposes an optimized description, prints a
    before/after summary and a unified diff, and writes to SKILL.md ONLY on accept
    (``--yes`` to auto-accept, ``--dry-run`` to never write). A declined or dry run
    leaves SKILL.md untouched -- the optimized description moves content_hash, so the
    write is always reviewed.
    """
    if not args.ack:
        print("FAIL: `skillcard optimize` makes live `claude -p` calls (spends tokens). "
              "Re-run with --i-understand-this-spends-tokens.")
        return 2
    if shutil.which("claude") is None:
        print("FAIL: `claude` CLI not found on PATH; `skillcard optimize` needs it.")
        return 1
    skill_dir = Path(args.skill_dir)
    if not (skill_dir / "SKILL.md").exists():
        print(f"FAIL: {skill_dir}: no SKILL.md to optimize")
        return 1

    try:
        result = run_optimize(
            skill_dir, args.model, workers=args.workers, timeout=args.timeout,
            runs_per_query=args.runs_per_query, max_iterations=args.max_iterations,
            workspace_base=args.workspace_base,
        )
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    b, a = result["before"], result["after"]
    print(f"optimize: {result['skill_name']} -- {result['iterations']} iteration(s)")
    print(f"  before: {b['passed']}/{b['total']} pass  "
          f"(precision={_fmt(b['precision'])} recall={_fmt(b['recall'])})")
    print(f"  after:  {a['passed']}/{a['total']} pass  "
          f"(precision={_fmt(a['precision'])} recall={_fmt(a['recall'])})")
    print(f"  harness: {result['harness']}")

    if not result["improved"]:
        print("OK: no improvement over the current description; SKILL.md left untouched.")
        return 0

    old = [ln + "\n" for ln in textwrap.wrap(result["original"], 88)] or ["\n"]
    new = [ln + "\n" for ln in textwrap.wrap(result["proposed"], 88)] or ["\n"]
    print("\nProposed description change:")
    print("".join(difflib.unified_diff(
        old, new, fromfile="description (current)", tofile="description (proposed)",
    )))

    if args.dry_run:
        print("DRY RUN: SKILL.md left untouched (re-run without --dry-run to apply).")
        return 0
    if args.yes:
        accept = True
    else:
        try:
            reply = input("Apply this description to SKILL.md? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        accept = reply in ("y", "yes")
    if not accept:
        print("Declined: SKILL.md left untouched.")
        return 0

    _write_description(skill_dir, result["proposed"])
    print(f"OK: wrote optimized description to {skill_dir / 'SKILL.md'}.")
    print("  content_hash will change -- re-run `skillcard build` + sign off review.")
    print(f"  provenance: {result['harness']}")
    return 0
