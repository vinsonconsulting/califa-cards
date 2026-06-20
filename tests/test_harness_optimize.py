"""Optimize harness: eval-set sourcing, the reviewed SKILL.md write, and the
measure -> propose -> pick-best loop -- all offline (injected stubs, no ``claude``)."""

import types

from skillcard.cli import parse_frontmatter
from skillcard.harness.optimize import (
    _eval_set_from_skill,
    _write_description,
    run_optimize,
    run_optimize_command,
)
from skillcard.harness.trigger import parse_skill_md

SKILL_MD = '''---
name: demo
version: "1.0.0"
summary: A demo skill.
description: >-
  Original description that we will optimize. Use when the user mentions demo
  things and wants the demo behavior.
output: { type: Code }
triggers:
  positive:
    - "do the demo thing"
    - "another demo request"
  negative:
    - { prompt: "unrelated request", use_instead: other }
---
# demo

Body content stays untouched.
'''


def _make_skill(tmp_path):
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(SKILL_MD)
    return skill


# --- eval-set sourcing -------------------------------------------------------

def test_eval_set_derives_from_frontmatter_triggers(tmp_path):
    skill = _make_skill(tmp_path)
    eval_set = _eval_set_from_skill(skill)
    assert {(e["query"], e["should_trigger"]) for e in eval_set} == {
        ("do the demo thing", True),
        ("another demo request", True),
        ("unrelated request", False),
    }


def test_eval_set_prefers_triggering_jsonl(tmp_path):
    skill = _make_skill(tmp_path)
    evals = skill / "evals"
    evals.mkdir()
    (evals / "triggering.jsonl").write_text(
        '{"query": "from jsonl", "should_trigger": true}\n'
    )
    assert _eval_set_from_skill(skill) == [{"query": "from jsonl", "should_trigger": True}]


# --- the reviewed write ------------------------------------------------------

def test_write_description_preserves_other_fields_and_body(tmp_path):
    skill = _make_skill(tmp_path)
    _write_description(skill, "Brand new optimized description for the demo skill.")
    text = (skill / "SKILL.md").read_text()
    fm = parse_frontmatter(text)
    assert " ".join(fm["description"].split()) == (
        "Brand new optimized description for the demo skill."
    )
    # Untouched neighbours and body.
    assert fm["name"] == "demo"
    assert fm["summary"] == "A demo skill."
    assert fm["triggers"]["positive"] == ["do the demo thing", "another demo request"]
    assert "Body content stays untouched." in text


def test_write_description_is_idempotent(tmp_path):
    skill = _make_skill(tmp_path)
    _write_description(skill, "A stable optimized description.")
    once = (skill / "SKILL.md").read_text()
    _write_description(skill, "A stable optimized description.")
    assert (skill / "SKILL.md").read_text() == once


def test_write_description_handles_single_line_form(tmp_path):
    skill = tmp_path / "s"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: s\ndescription: short one.\noutput: x\n---\n# s\nbody\n"
    )
    _write_description(skill, "a replacement.")
    fm = parse_frontmatter((skill / "SKILL.md").read_text())
    assert fm["description"].strip() == "a replacement."
    assert fm["output"] == "x"
    assert "body" in (skill / "SKILL.md").read_text()


# --- the loop ----------------------------------------------------------------

def _measure_from(scores):
    """measure(desc) stub: looks up (passed, total) and shapes a run_eval result."""
    def measure(desc):
        passed, total = scores[desc]
        return {
            "description": desc,
            "results": [],
            "summary": {
                "passed": passed, "total": total, "failed": total - passed,
                "fp": 0, "precision": 1.0,
                "recall": (passed / total if total else None),
            },
        }
    return measure


def _propose_from(seq):
    """propose(desc, ev, hist) stub: yields seq, then echoes desc to stop the loop."""
    it = iter(seq)

    def propose(desc, ev, hist):
        return next(it, desc)
    return propose


def test_run_optimize_picks_the_best_candidate(tmp_path):
    skill = _make_skill(tmp_path)
    _, original, _ = parse_skill_md(skill)
    res = run_optimize(
        skill, "m", max_iterations=3,
        measure=_measure_from({original: (1, 3), "better one": (3, 3)}),
        propose=_propose_from(["better one"]),
    )
    assert res["proposed"] == "better one"
    assert res["improved"] is True
    assert res["before"]["passed"] == 1
    assert res["after"]["passed"] == 3
    assert res["iterations"] == 1
    assert res["harness"].startswith("skill-eval-fork@")


def test_run_optimize_keeps_original_when_no_gain(tmp_path):
    skill = _make_skill(tmp_path)
    _, original, _ = parse_skill_md(skill)
    res = run_optimize(
        skill, "m", max_iterations=3,
        measure=_measure_from({original: (2, 3), "worse": (1, 3)}),
        propose=_propose_from(["worse"]),
    )
    assert res["improved"] is False
    assert res["proposed"] == original


# --- the command: reviewed write only on accept ------------------------------

def _args(skill, **over):
    base = dict(
        skill_dir=str(skill), model="m", workers=1, runs_per_query=1, timeout=1,
        max_iterations=1, yes=False, dry_run=False, ack=True, workspace_base=None,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _patch_optimize(monkeypatch, skill):
    _, original, _ = parse_skill_md(skill)
    result = {
        "skill_name": "demo", "original": original, "proposed": "NEW DESCRIPTION.",
        "improved": True, "iterations": 1,
        "before": {"passed": 1, "total": 3, "precision": 1.0, "recall": 0.33},
        "after": {"passed": 3, "total": 3, "precision": 1.0, "recall": 1.0},
        "history": [], "model": "m", "date": "2026-06-20",
        "harness": "skill-eval-fork@ef6f952 / m / 2026-06-20",
    }
    monkeypatch.setattr("skillcard.harness.optimize.run_optimize", lambda *a, **k: result)
    monkeypatch.setattr("skillcard.harness.optimize.shutil.which", lambda _n: "/bin/claude")
    return original


def test_command_requires_token_ack(tmp_path):
    skill = _make_skill(tmp_path)
    assert run_optimize_command(_args(skill, ack=False)) == 2


def test_command_decline_leaves_skill_md_untouched(tmp_path, monkeypatch):
    skill = _make_skill(tmp_path)
    original = _patch_optimize(monkeypatch, skill)
    monkeypatch.setattr("builtins.input", lambda _p: "n")
    before = (skill / "SKILL.md").read_text()
    assert run_optimize_command(_args(skill)) == 0
    assert (skill / "SKILL.md").read_text() == before
    assert parse_frontmatter(before)["description"].split() == original.split()


def test_command_dry_run_never_writes(tmp_path, monkeypatch):
    skill = _make_skill(tmp_path)
    _patch_optimize(monkeypatch, skill)
    before = (skill / "SKILL.md").read_text()
    assert run_optimize_command(_args(skill, dry_run=True)) == 0
    assert (skill / "SKILL.md").read_text() == before


def test_command_accept_writes_description(tmp_path, monkeypatch):
    skill = _make_skill(tmp_path)
    _patch_optimize(monkeypatch, skill)
    monkeypatch.setattr("builtins.input", lambda _p: "y")
    assert run_optimize_command(_args(skill)) == 0
    assert parse_frontmatter((skill / "SKILL.md").read_text())["description"].strip() == (
        "NEW DESCRIPTION."
    )
