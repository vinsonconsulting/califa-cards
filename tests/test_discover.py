"""Discover tests: a skill dir becomes a validatable card context.

discover() is a pure read of a skill bundle. It assembles identity from SKILL.md
frontmatter and governance from the ``card.authored.yaml`` sidecar, plus repo
config, the scan report, the evals JSON, and git/hashing -- and leaves genuinely
missing required fields absent, so build_card's schema validation is the single
refusal point.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from schema.schema import SkillCard
from skillcard.discover import discover

# SKILL.md frontmatter: the skill's identity (hashed surface).
IDENTITY = {
    "name": "textual",
    "version": "1.2.0",
    "description": (
        "Build, style, and debug terminal user interfaces in Python with Textual. "
        "Use when the user mentions Textual."
    ),
    "summary": "Build and debug Python TUIs with Textual.",
    "output": {"type": "Code", "format": "Markdown with Python + TCSS code blocks"},
    "dependencies": ["textual>=0.80,<1.0", "python>=3.9"],
    "external_endpoints": "none",
    "permissions": {"network": False, "shell": True, "file": True, "env": False, "mcp": False},
    "card_version": "1.0",
    "triggers": {
        "positive": ["build a Textual app with a data table and a footer"],
        "negative": [{"prompt": "parse command-line flags", "use_instead": "click-cli"}],
    },
}
# card.authored.yaml: the authored governance overlay (NOT hashed).
SIDECAR = {
    "status": "stable",
    "source_commit": "9f3a1c2",
    "updated": "2026-06-18",
    "accepted_findings": [
        {"id": "AST4", "note": "subprocess invokes textual run and pytest"},
    ],
}
REPO_CFG = (
    'owner = "@vinsonconsulting"\n'
    'tier = "public"\n'
    'url = "https://github.com/vinsonconsulting/claude-skill-foundry"\n'
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
    root: Path,
    *,
    with_results: bool = True,
    identity_overrides: dict | None = None,
    sidecar_overrides: dict | None = None,
) -> Path:
    skill = root / "textual"
    skill.mkdir()
    ident = json.loads(json.dumps(IDENTITY))  # deep copy
    if identity_overrides is not None:
        ident.update(identity_overrides)
    side = json.loads(json.dumps(SIDECAR))
    if sidecar_overrides is not None:
        side.update(sidecar_overrides)
    front = yaml.safe_dump(ident, sort_keys=False)
    (skill / "SKILL.md").write_text(f"---\n{front}---\n# {ident['name']}\n", encoding="utf-8")
    (skill / "card.authored.yaml").write_text(
        yaml.safe_dump(side, sort_keys=False), encoding="utf-8"
    )
    (skill / ".skillcard.toml").write_text(REPO_CFG, encoding="utf-8")
    (skill / "scan.json").write_text(json.dumps(SCAN), encoding="utf-8")
    evals = skill / "evals"
    evals.mkdir()
    payload = dict(EVALS) if with_results else {"evals": []}
    (evals / "evals.json").write_text(json.dumps(payload), encoding="utf-8")
    return skill


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin",
}


def _git(repo: Path):
    def run(*a, text=False):
        return subprocess.run(
            ["git", "-C", str(repo), *a], check=True, env=_GIT_ENV, capture_output=True, text=text
        )

    return run


def test_discover_assembles_a_valid_stable_card(tmp_path):
    skill = _make_skill(tmp_path)
    card = SkillCard.model_validate(discover(skill).card)  # refuses if anything is off
    assert card.name == "textual"
    assert card.summary == "Build and debug Python TUIs with Textual."
    assert card.owner == "@vinsonconsulting"
    assert card.repo.url.endswith("claude-skill-foundry")
    assert card.permissions.shell is True  # security surface read from SKILL.md identity
    assert card.scan.tool == "skillspector@a5092dd"
    assert card.scan.score == 12 and card.scan.severity == "LOW"
    assert card.scan.date.isoformat() == "2026-06-17"
    # content_hash is real (computed over the fixture's source files).
    assert card.content_hash.startswith("sha256:")
    # source_commit/updated honored the sidecar pin (git-independent).
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


def test_discover_merges_sidecar_finding_decision(tmp_path):
    skill = _make_skill(tmp_path)
    f = SkillCard.model_validate(discover(skill).card).scan.findings[0]
    assert f.rule_id == "AST4"
    assert f.atlas == "AML.T0050" and f.owasp is None  # parsed from issue tags
    assert f.status == "accepted" and f.note.startswith("subprocess")  # sidecar decision


def test_metrics_notes_sourced_from_sidecar(tmp_path):
    skill = _make_skill(
        tmp_path, sidecar_overrides={"metrics_notes": "recall is a harness-floor artifact"}
    )
    card = SkillCard.model_validate(discover(skill).card)
    assert card.metrics.notes == "recall is a harness-floor artifact"


def test_beta_path_no_results_means_no_metrics(tmp_path):
    skill = _make_skill(tmp_path, with_results=False, sidecar_overrides={"status": "beta"})
    card = SkillCard.model_validate(discover(skill).card)
    assert card.metrics is None


def test_provenance_marks_authored_fields_human(tmp_path):
    skill = _make_skill(tmp_path)
    prov = discover(skill).provenance
    assert prov["summary"] == "human"
    assert prov["triggers"] == "human"
    assert prov["permissions"] == "human"
    assert prov["status"] == "human"
    assert prov["description"] == "inferred"
    assert prov["content_hash"] == "inferred"


def test_missing_skill_md_is_a_clear_error(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError, match="SKILL.md"):
        discover(tmp_path / "empty")


def test_missing_sidecar_leaves_status_absent(tmp_path):
    # No card.authored.yaml: discover leaves required `status` absent so schema
    # validation is the single refusal point (the leave-missing-absent contract).
    skill = _make_skill(tmp_path)
    (skill / "card.authored.yaml").unlink()
    assert discover(skill).card["status"] is None


def test_source_commit_falls_back_to_git(tmp_path):
    # When the sidecar does not pin source_commit, discover derives it from the
    # last commit touching the skill's *source* files.
    skill = _make_skill(tmp_path, sidecar_overrides={"source_commit": None, "updated": None})
    run = _git(tmp_path)
    run("init")
    run("add", "-A")
    run("commit", "-m", "init")
    head = run("rev-parse", "HEAD", text=True).stdout.strip()
    card = SkillCard.model_validate(discover(skill).card)
    assert card.source_commit == head


def test_sidecar_edit_preserves_code_identity(tmp_path):
    """The ruling's acceptance gate.

    Editing an authored governance field (status, a finding note) must NOT move
    ``content_hash`` or ``source_commit`` -- those describe the *code* -- while
    ``card.json`` itself must reflect the change. This is the test that would
    have caught the latent bug of governance data living on the hashed surface.
    """
    skill = _make_skill(tmp_path, sidecar_overrides={"source_commit": None, "updated": None})
    run = _git(tmp_path)
    run("init")
    run("add", "-A")
    run("commit", "-m", "init")

    before = SkillCard.model_validate(discover(skill).card)

    # Flip status and rewrite a finding note, then *commit* only the sidecar.
    side_path = skill / "card.authored.yaml"
    side = yaml.safe_load(side_path.read_text(encoding="utf-8"))
    side["status"] = "beta"
    side["accepted_findings"][0]["note"] = "updated justification"
    side_path.write_text(yaml.safe_dump(side, sort_keys=False), encoding="utf-8")
    run("add", "-A")
    run("commit", "-m", "tweak governance")  # touches no *source* file

    after = SkillCard.model_validate(discover(skill).card)

    # Identity is unmoved: the sidecar is excluded from the hash manifest, and the
    # governance commit touched no source file, so source_commit still points at init.
    assert after.content_hash == before.content_hash
    assert after.source_commit == before.source_commit
    # Governance did change in the canonical card.
    assert before.status == "stable" and after.status == "beta"
    assert after.scan.findings[0].note == "updated justification"
    assert before.scan.findings[0].note != after.scan.findings[0].note
