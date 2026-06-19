"""CLI tests for `skillcard build` and `skillcard review` end to end."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from skillcard import cli

SKILL_MD = {
    "name": "demo",
    "version": "0.1.0",
    "description": "A demo skill used in tests. Use when testing the generator.",
    "card": {
        "summary": "A demo skill.",
        "status": "beta",
        "source_commit": "abc1234",
        "updated": "2026-06-18",
        "output": {"type": "Code", "format": "Markdown"},
        "dependencies": ["python>=3.12"],
        "external_endpoints": "none",
        "permissions": {"network": False, "shell": False, "file": True, "env": False, "mcp": False},
        "triggers": {
            "positive": ["do the demo thing"],
            "negative": [{"prompt": "do a different thing", "use_instead": "other-skill"}],
        },
    },
}
REPO_CFG = 'owner = "@me"\ntier = "public"\nurl = "https://example.com/repo"\nlicense = "MIT"\n'
SCAN = {"risk_assessment": {"score": 0}, "skill": {"scanned_at": "2026-06-17T00:00:00Z"},
        "issues": [], "metadata": {"skillspector_version": "2.2.3"}}


def _make_skill(tmp_path: Path, card_overrides: dict | None = None) -> Path:
    skill = tmp_path / "demo"
    skill.mkdir()
    md = json.loads(json.dumps(SKILL_MD))
    if card_overrides:
        md["card"].update(card_overrides)
    (skill / "SKILL.md").write_text(
        "---\n" + yaml.safe_dump(md, sort_keys=False) + "---\n# demo\n", encoding="utf-8"
    )
    (skill / ".skillcard.toml").write_text(REPO_CFG, encoding="utf-8")
    (skill / "scan.json").write_text(json.dumps(SCAN), encoding="utf-8")
    return skill


def test_build_generates_card_md_and_review(tmp_path):
    skill = _make_skill(tmp_path)
    code = cli.main(["build", str(skill)])
    assert (skill / "card.json").exists()
    assert (skill / "skill-card.md").exists()
    assert (skill / "card-review.md").exists()
    # Freshly built, the HUMAN rows are un-ticked, so the gate (and build) fail.
    assert code != 0
    assert cli.main(["validate", str(skill)]) == 0  # but the card itself is valid


def test_build_is_idempotent_via_cli(tmp_path):
    skill = _make_skill(tmp_path)
    cli.main(["build", str(skill)])
    first = (skill / "card.json").read_bytes(), (skill / "skill-card.md").read_bytes()
    cli.main(["build", str(skill)])
    assert ((skill / "card.json").read_bytes(), (skill / "skill-card.md").read_bytes()) == first


def test_review_passes_after_ticking(tmp_path):
    skill = _make_skill(tmp_path)
    cli.main(["build", str(skill)])
    review = skill / "card-review.md"
    review.write_text(review.read_text().replace("- [ ]", "- [x]"), encoding="utf-8")
    assert cli.main(["review", str(skill)]) == 0


def test_build_refuses_missing_authored_field(tmp_path, capsys):
    # Drop an authored required field: build must refuse, naming it, writing nothing.
    skill = _make_skill(tmp_path, card_overrides={"permissions": None})
    code = cli.main(["build", str(skill)])
    assert code == 1
    assert "permissions" in capsys.readouterr().out
    assert not (skill / "card.json").exists()


def test_build_reports_missing_scan_report_cleanly(tmp_path, capsys):
    # A skill that has not been scanned yet: clean message + exit 1, no traceback.
    skill = _make_skill(tmp_path)
    (skill / "scan.json").unlink()
    code = cli.main(["build", str(skill)])
    assert code == 1
    out = capsys.readouterr().out
    assert "scan report" in out
