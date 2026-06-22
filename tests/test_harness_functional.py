"""Functional orchestrator: generate (stubbed) -> grade -> aggregate, no claude.

Builds a tiny skill with a real 2-assertion grader and injects a ``generate``
stub, so the grade + aggregation path runs offline. Pins the aggregation:
``eval_pass_rate`` = mean per-task pass-rate, ``task_completion_rate`` = fraction
of tasks fully passing.
"""

import json

from skillcard.harness import run_functional
from skillcard.harness.functional import _extract_artifact

GRADERS = '''
def grade(task_id, text, cfg):
    exps = [
        {"text": "has hello", "passed": "hello" in text, "evidence": ""},
        {"text": "has world", "passed": "world" in text, "evidence": ""},
    ]
    passed = sum(1 for e in exps if e["passed"])
    return {"expectations": exps,
            "summary": {"passed": passed, "total": len(exps), "pass_rate": passed / len(exps)}}
'''

RUN_GRADER = '''
import argparse, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import graders


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--readme")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    tasks = {t["id"]: t for t in json.loads((HERE / "tasks.json").read_text())["tasks"]}
    text = Path(a.readme).read_text()
    result = graders.grade(a.task, text, tasks[a.task].get("grader_config", {}))
    out = json.dumps(result, indent=2)
    if a.out:
        Path(a.out).write_text(out)
    print(out)
    s = result["summary"]
    return 0 if s["passed"] == s["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def _make_skill(tmp_path):
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: A demo skill.\n---\n# demo\n")
    func = skill / "evals" / "functional"
    func.mkdir(parents=True)
    (func / "tasks.json").write_text(json.dumps({"skill_name": "demo", "tasks": [
        {"id": "hello", "name": "hello", "prompt": "write hello world",
         "fixtures": [], "grader_config": {}}]}))
    (func / "graders.py").write_text(GRADERS)
    (func / "run_grader.py").write_text(RUN_GRADER)
    return skill


def test_functional_all_pass(tmp_path):
    skill = _make_skill(tmp_path)
    out = run_functional(skill, generate=lambda task: "hello world")
    assert out["eval_pass_rate"] == 1.0
    assert out["task_completion_rate"] == 1.0
    assert out["tasks_passed"] == "1/1"


def test_functional_partial_fail(tmp_path):
    skill = _make_skill(tmp_path)
    out = run_functional(skill, generate=lambda task: "hello, no second word")
    assert out["eval_pass_rate"] == 0.5  # 1 of 2 assertions
    assert out["task_completion_rate"] == 0.0  # task did not fully pass


def test_best_of_keeps_the_best_generation(tmp_path):
    # First generation fails an assertion, the second is clean. best_of=2 keeps the
    # better run, so the task reaches 1.0/1.0; best_of=1 sees only the first (0.5/0.0).
    skill = _make_skill(tmp_path)
    outputs = iter(["hello, no second word", "hello world"])

    def generate(task):
        return next(outputs)

    out = run_functional(skill, generate=generate, best_of=2)
    assert out["eval_pass_rate"] == 1.0
    assert out["task_completion_rate"] == 1.0


def test_best_of_default_is_single_shot(tmp_path):
    # Default best_of=1 runs the cycle exactly once: the single-shot path is unchanged.
    skill = _make_skill(tmp_path)
    calls = []

    def generate(task):
        calls.append(task["id"])
        return "hello, no second word"

    out = run_functional(skill, generate=generate)
    assert len(calls) == 1  # one generation per task, as before
    assert out["eval_pass_rate"] == 0.5 and out["task_completion_rate"] == 0.0


def test_no_functional_dir_returns_none(tmp_path):
    skill = tmp_path / "bare"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bare\ndescription: x\n---\n")
    assert run_functional(skill, generate=lambda t: "") is None


# --- artifact extraction: grade the deliverable, not the conversational wrapper ---

def test_extract_artifact_prefers_written_file(tmp_path):
    # The skill wrote its real deliverable; the wrapper prose is irrelevant.
    (tmp_path / "README.md").write_text("# Real deliverable\nhello world\n")
    out = _extract_artifact(tmp_path, "Sure! Here's your polished README!", "README.md")
    assert out == "# Real deliverable\nhello world\n"


def test_extract_artifact_falls_back_to_fenced_block(tmp_path):
    # No file written: recover the README from the largest fenced block in stdout.
    stdout = "Sure! Here's the README:\n\n```markdown\n# Title\nbody\n```\n\nEnjoy!"
    assert _extract_artifact(tmp_path, stdout, "README.md") == "# Title\nbody\n"


def test_extract_artifact_falls_back_to_raw_stdout(tmp_path):
    # No file, no fence: degrade to raw stdout rather than crash.
    assert _extract_artifact(tmp_path, "just prose", "README.md") == "just prose"


def test_extract_artifact_ignores_empty_file(tmp_path):
    (tmp_path / "README.md").write_text("   \n")
    assert _extract_artifact(tmp_path, "fallback prose", "README.md") == "fallback prose"


# --- skill install: the model must get SKILL.md AND the reference docs ---

def _skill_with_refs(tmp_path, ref_name):
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n# demo\n")
    refs = skill / ref_name
    refs.mkdir()
    (refs / "layout.md").write_text("layout docs")
    return skill


def test_install_skill_copies_references_plural(tmp_path):
    # Skills use the plural `references/` (Anthropic convention); the eval
    # workspace must carry them so the model can open them on demand.
    from skillcard.harness.functional import _install_skill

    skill = _skill_with_refs(tmp_path, "references")
    dest = tmp_path / "install" / "demo"
    _install_skill(skill, dest)
    assert (dest / "SKILL.md").is_file()
    assert (dest / "references" / "layout.md").read_text() == "layout docs"


def test_install_skill_copies_reference_singular(tmp_path):
    # The singular `reference/` (e.g. github-readme) is still honored.
    from skillcard.harness.functional import _install_skill

    skill = _skill_with_refs(tmp_path, "reference")
    dest = tmp_path / "install" / "demo"
    _install_skill(skill, dest)
    assert (dest / "reference" / "layout.md").read_text() == "layout docs"


def test_install_skill_without_refs_copies_only_skill_md(tmp_path):
    from skillcard.harness.functional import _install_skill

    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n# demo\n")
    dest = tmp_path / "install" / "demo"
    _install_skill(skill, dest)
    assert (dest / "SKILL.md").is_file()
    assert not (dest / "reference").exists()
    assert not (dest / "references").exists()
