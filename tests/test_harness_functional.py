"""Functional orchestrator: generate (stubbed) -> grade -> aggregate, no claude.

Builds a tiny skill with a real 2-assertion grader and injects a ``generate``
stub, so the grade + aggregation path runs offline. Pins the aggregation:
``eval_pass_rate`` = mean per-task pass-rate, ``task_completion_rate`` = fraction
of tasks fully passing.
"""

import json

from skillcard.harness import run_functional

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


def test_no_functional_dir_returns_none(tmp_path):
    skill = tmp_path / "bare"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: bare\ndescription: x\n---\n")
    assert run_functional(skill, generate=lambda t: "") is None
