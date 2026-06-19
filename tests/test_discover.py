"""Discover tests: a skill dir becomes a validatable card context.

discover() is a pure read of a skill bundle. It assembles what it can from
SKILL.md frontmatter (the authored ``card:`` block), repo config, the scan
report, the evals JSON, and git/hashing -- and leaves genuinely missing required
fields absent, so build_card's schema validation is the single refusal point.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from schema.schema import SkillCard
from skillcard.discover import discover

# The textual fixture, authored inline so the test owns its inputs.
SKILL_MD = {
    "name": "textual",
    "version": "1.2.0",
    "description": (
        "Build, style, and debug terminal user interfaces in Python with Textual. "
        "Use when the user mentions Textual."
    ),
    "card": {
        "summary": "Build and debug Python TUIs with Textual.",
        "status": "stable",
        "source_commit": "9f3a1c2",
        "updated": "2026-06-18",
        "output": {"type": "Code", "format": "Markdown with Python + TCSS code blocks"},
        "dependencies": ["textual>=0.80,<1.0", "python>=3.9"],
        "external_endpoints": "none",
        "permissions": {"network": False, "shell": True, "file": True, "env": False, "mcp": False},
        "triggers": {
            "positive": ["build a Textual app with a data table and a footer"],
            "negative": [{"prompt": "parse command-line flags", "use_instead": "click-cli"}],
        },
        "findings": {
            "AST4": {"status": "accepted", "note": "subprocess invokes textual run and pytest"},
        },
    },
}
REPO_CFG = (
    'owner = "@vinsonconsulting"\n'
    'tier = "public"\n'
    'url = "https://github.com/vinsonconsulting/jims-filing-cabinet-of-claude-skills"\n'
    'license = "MIT"\n'
    'scan_tool = "skillspector@a5092dd"\n'
)
SCAN = {
    "risk_assessment": {"score": 12, "severity": "LOW"},
    "skill": {"scanned_at": "2026-06-17T00:00:00+00:00"},
    "issues": [{"id": "AST4", "severity": "MEDIUM", "tags": ["AML.T0050"]}],
    "metadata": {"skillspector_version": "2.2.3"},
}
EVALS = {
    "results": {
        "triggering": {"precision": 0.95, "recall": 0.88, "near_miss_precision": 1.0},
        "functional": {"eval_pass_rate": 0.86, "task_completion_rate": 0.83},
        "harness": "skill-creator@b0cbd3d / claude-opus-4-8 / 2026-06-17",
    }
}


def _make_skill(
    root: Path, *, with_results: bool = True, card_overrides: dict | None = None
) -> Path:
    skill = root / "textual"
    skill.mkdir()
    skill_md = dict(SKILL_MD)
    if card_overrides is not None:
        skill_md = json.loads(json.dumps(skill_md))  # deep copy
        skill_md["card"].update(card_overrides)
    front = yaml.safe_dump(skill_md, sort_keys=False)
    (skill / "SKILL.md").write_text(f"---\n{front}---\n# {skill_md['name']}\n", encoding="utf-8")
    (skill / ".skillcard.toml").write_text(REPO_CFG, encoding="utf-8")
    (skill / "scan.json").write_text(json.dumps(SCAN), encoding="utf-8")
    evals = skill / "evals"
    evals.mkdir()
    payload = dict(EVALS) if with_results else {"evals": []}
    (evals / "evals.json").write_text(json.dumps(payload), encoding="utf-8")
    return skill


def test_discover_assembles_a_valid_stable_card(tmp_path):
    skill = _make_skill(tmp_path)
    result = discover(skill)
    card = SkillCard.model_validate(result.card)  # refuses if anything is off
    assert card.name == "textual"
    assert card.summary == "Build and debug Python TUIs with Textual."
    assert card.owner == "@vinsonconsulting"
    assert card.repo.url.endswith("jims-filing-cabinet-of-claude-skills")
    assert card.scan.tool == "skillspector@a5092dd"
    assert card.scan.score == 12 and card.scan.severity == "LOW"
    assert card.scan.date.isoformat() == "2026-06-17"
    # content_hash is real (computed over the fixture's source files).
    assert card.content_hash.startswith("sha256:")
    # source_commit/updated honored the card: block pin (git-independent).
    assert card.source_commit == "9f3a1c2"
    assert card.updated.isoformat() == "2026-06-18"


def test_discover_maps_evals_results_into_metrics(tmp_path):
    skill = _make_skill(tmp_path)
    card = SkillCard.model_validate(discover(skill).card)
    assert card.metrics is not None
    assert card.metrics.trigger_precision == 0.95
    assert card.metrics.near_miss_precision == 1.0
    assert card.metrics.eval_pass_rate == 0.86
    assert card.metrics.harness.startswith("skill-creator@b0cbd3d")


def test_discover_merges_human_finding_decision(tmp_path):
    skill = _make_skill(tmp_path)
    f = SkillCard.model_validate(discover(skill).card).scan.findings[0]
    assert f.rule_id == "AST4"
    assert f.atlas == "AML.T0050" and f.owasp is None  # parsed from issue tags
    assert f.status == "accepted" and f.note.startswith("subprocess")  # human decision


def test_beta_path_no_results_means_no_metrics(tmp_path):
    skill = _make_skill(tmp_path, with_results=False, card_overrides={"status": "beta"})
    card = SkillCard.model_validate(discover(skill).card)
    assert card.metrics is None


def test_provenance_marks_authored_fields_human(tmp_path):
    skill = _make_skill(tmp_path)
    prov = discover(skill).provenance
    assert prov["summary"] == "human"
    assert prov["triggers"] == "human"
    assert prov["permissions"] == "human"
    assert prov["description"] == "inferred"
    assert prov["content_hash"] == "inferred"


def test_missing_skill_md_is_a_clear_error(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="SKILL.md"):
        discover(tmp_path / "empty")


def test_source_commit_falls_back_to_git(tmp_path):
    # When the card: block does not pin source_commit, discover derives it from
    # the last commit touching the skill's *source* files.
    skill = _make_skill(tmp_path, card_overrides={"source_commit": None, "updated": None})
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin",
    }

    def run(*a, text=False):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *a], check=True, env=env, capture_output=True, text=text
        )

    run("init")
    run("add", "-A")
    run("commit", "-m", "init")
    head = run("rev-parse", "HEAD", text=True).stdout.strip()
    card = SkillCard.model_validate(discover(skill).card)
    assert card.source_commit == head
