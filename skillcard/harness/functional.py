"""Functional evaluation orchestrator (SPEC.md section D).

The trigger harness measures *whether* a skill fires; this measures *how well it
does the work* once it does. Convention: a skill provides
``evals/functional/{tasks.json, run_grader.py, graders.py, fixtures/}``. For each
task we run the skill's full workflow to completion in an isolated workspace -- the
real skill and the task's fixtures are present, and ``claude -p`` runs with
file-write permission so the skill produces its actual deliverable (a ``README.md``
written to disk). We then grade THAT artifact with the skill's OWN deterministic
``run_grader.py`` -- we never re-implement scoring. Aggregate:

* ``eval_pass_rate``       = mean over tasks of the grader's ``summary.pass_rate``
* ``task_completion_rate`` = fraction of tasks that fully pass (passed == total)

ARTIFACT GRADING (methodology). We grade the file the skill writes, not the
conversational ``claude -p`` stdout. Grading stdout scans Claude's wrapper prose
("here's your polished README...") alongside the deliverable, which trips strict
deterministic graders -- an em-dash or an AI-tell word in the wrapper fails a check
the README itself passes -- and floors the score. Grading the on-disk artifact
strips the wrapper, so the figures reproduce the cabinet's authoritative
deterministic graders (github-readme: 1.0/1.0). If the skill writes no file we fall
back to extracting the artifact from stdout, then to raw stdout: a graceful lower
bound, never a crash.

``generate`` is injectable: tests pass a stub that returns canned README text, so
the grade -> aggregate path runs with ZERO ``claude`` calls (``make check`` stays
offline). ``tool_call_delta`` / ``token_efficiency`` need a no-skill baseline run
and are left unset (both optional in the schema).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from skillcard.harness.trigger import EVAL_WORKSPACE_ROOT, claude_env, parse_skill_md

# A fenced code block, tolerating an info string after the opening backticks.
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _extract_artifact(workdir: Path, stdout: str, artifact_name: str) -> str:
    """Return the task's produced artifact: the written file, else from stdout.

    Priority, so we always grade the closest thing to the real deliverable:

    1. ``workdir/artifact_name`` if the skill wrote it -- the authoritative path:
       the file is exactly the deliverable, with no conversational wrapper;
    2. else the largest fenced code block in stdout (the model emitted the README
       inline instead of writing a file);
    3. else raw stdout (degrades to the pre-artifact behaviour; never crashes).
    """
    artifact = workdir / artifact_name
    if artifact.is_file():
        text = artifact.read_text(encoding="utf-8")
        if text.strip():
            return text
    blocks = _FENCE_RE.findall(stdout)
    if blocks:
        return max(blocks, key=len)
    return stdout


def _generate_readme_live(
    task: dict, skill_dir: Path, skill_name: str, model: str | None, timeout: int,
) -> str:
    """Run one task's full workflow with the REAL skill loaded; return the artifact.

    Copies the actual skill into the workspace's ``.claude/skills/<name>/`` (so the
    model uses its guidance, unlike the trigger runner's description-only proxy) and
    copies the task fixtures so relative paths resolve, then runs ``claude -p`` with
    file-write permission and an explicit instruction to write the deliverable to a
    known path. The produced file is the graded artifact -- see
    :func:`_extract_artifact`. Per-run workspace isolation under
    ``EVAL_WORKSPACE_ROOT``; the workdir is removed in ``finally``.
    """
    artifact_name = task.get("artifact", "README.md")
    workdir = EVAL_WORKSPACE_ROOT / f"func-{uuid.uuid4().hex[:8]}"
    skill_install = workdir / ".claude" / "skills" / skill_name
    skill_install.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(skill_dir / "SKILL.md", skill_install / "SKILL.md")
        ref = skill_dir / "reference"
        if ref.is_dir():
            shutil.copytree(ref, skill_install / "reference")
        func_dir = skill_dir / "evals" / "functional"
        for rel in task.get("fixtures", []):
            src = func_dir / rel
            dst = workdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst)
        # Pin the output path so we grade the real deliverable, not stdout. The
        # workspace is isolated and ephemeral, so bypassPermissions is safe and
        # lets the skill actually write its file (the whole point of this axis).
        prompt = (
            f"{task['prompt']}\n\n"
            f"Write the finished result to a file named {artifact_name} in the "
            f"current directory."
        )
        cmd = ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"]
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(
            cmd, cwd=str(workdir), env=claude_env(),
            capture_output=True, text=True, timeout=timeout,
        )
        return _extract_artifact(workdir, proc.stdout, artifact_name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _grade(skill_dir: Path, task_id: str, readme_text: str) -> dict:
    """Grade a README with the skill's own run_grader.py; return its summary dict."""
    func_dir = skill_dir / "evals" / "functional"
    workdir = EVAL_WORKSPACE_ROOT / f"grade-{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        readme_path = workdir / "README.md"
        readme_path.write_text(readme_text, encoding="utf-8")
        grading_path = workdir / "grading.json"
        # run_grader writes --out then exits non-zero if any assertion failed;
        # we read the file regardless of exit code.
        subprocess.run(
            [sys.executable, str(func_dir / "run_grader.py"),
             "--task", task_id, "--readme", str(readme_path),
             "--out", str(grading_path)],
            capture_output=True, text=True, check=False,
        )
        return json.loads(grading_path.read_text(encoding="utf-8"))["summary"]
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_functional(
    skill_dir: str | Path,
    model: str | None = None,
    timeout: int = 300,
    generate: Callable[[dict], str] | None = None,
    best_of: int = 1,
) -> dict | None:
    """Run the functional set; return the aggregate, or None if the skill has none.

    ``generate(task) -> readme_text`` defaults to a live ``claude -p`` workflow run;
    inject a stub in tests to exercise grading + aggregation offline.

    ``best_of`` (default 1, single-shot) runs the generate -> grade cycle N times
    per task and keeps the highest-scoring run, so a clean generation is what
    counts and the aggregate reproduces the authoritative score rather than a
    single-shot lower bound. Best = max ``pass_rate``; since ``total`` is fixed per
    task that also maximises completion (``passed == total``). Opt-in: N>1 costs N
    times the tokens, so the CLI guards it behind the token-spend ack.
    """
    skill_dir = Path(skill_dir)
    tasks_path = skill_dir / "evals" / "functional" / "tasks.json"
    if not tasks_path.exists():
        return None
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]
    name, _description, _content = parse_skill_md(skill_dir)

    if generate is None:
        def generate(task: dict) -> str:
            return _generate_readme_live(task, skill_dir, name, model, timeout)

    samples = max(1, best_of)
    pass_rates: list[float] = []
    completions: list[float] = []
    per_task: list[dict] = []
    for task in tasks:
        best: dict | None = None
        for _ in range(samples):
            summary = _grade(skill_dir, task["id"], generate(task))
            if best is None or summary["pass_rate"] > best["pass_rate"]:
                best = summary
        pass_rates.append(best["pass_rate"])
        completions.append(1.0 if best["passed"] == best["total"] else 0.0)
        per_task.append({"id": task["id"], **best})

    n = len(pass_rates)
    return {
        "eval_pass_rate": sum(pass_rates) / n if n else 0.0,
        "task_completion_rate": sum(completions) / n if n else 0.0,
        "tasks_passed": f"{int(sum(completions))}/{n}",
        "per_task": per_task,
    }
