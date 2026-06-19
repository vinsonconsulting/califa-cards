"""CLI tests: content_hash, directory validation, and the gate warn flag."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from skillcard import cli, gate
from skillcard.hashing import content_hash

REPO = Path(__file__).resolve().parents[1]
TEXTUAL_JSON = REPO / "examples" / "textual" / "card.json"


def _card_dict() -> dict:
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def _write_skill(skill_dir: Path, card: dict) -> dict:
    """Lay down a source file plus an agreeing skill-card.md / card.json pair."""
    (skill_dir / "SKILL.md").write_text("# demo skill\n", encoding="utf-8")
    card = dict(card)
    card["content_hash"] = content_hash(skill_dir)
    (skill_dir / "card.json").write_text(json.dumps(card), encoding="utf-8")
    frontmatter = yaml.safe_dump(card, sort_keys=False)
    (skill_dir / "skill-card.md").write_text(f"---\n{frontmatter}---\n", encoding="utf-8")
    return card


def test_validate_skill_dir_ok(tmp_path):
    _write_skill(tmp_path, _card_dict())
    assert cli.main(["validate", str(tmp_path)]) == 0


def test_validate_dir_detects_disagreement(tmp_path):
    _write_skill(tmp_path, _card_dict())
    card = json.loads((tmp_path / "card.json").read_text(encoding="utf-8"))
    card["summary"] = "a different summary than the md has"
    (tmp_path / "card.json").write_text(json.dumps(card), encoding="utf-8")
    assert cli.main(["validate", str(tmp_path)]) == 1


def test_validate_dir_detects_hash_mismatch(tmp_path):
    _write_skill(tmp_path, _card_dict())
    # A new source file lands after the hash was stamped; md/json still agree.
    (tmp_path / "EXTRA.md").write_text("unstamped source\n", encoding="utf-8")
    assert cli.main(["validate", str(tmp_path)]) == 1


def test_hash_command_matches_helper(tmp_path, capsys):
    (tmp_path / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    assert cli.main(["hash", str(tmp_path)]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("sha256:")
    assert out == content_hash(tmp_path)


def _medium_report() -> dict:
    return {
        "risk_assessment": {"score": 35},
        "issues": [{"rule_id": "AST4", "severity": "MEDIUM"}],
    }


def test_gate_medium_without_card_fails(tmp_path):
    report = tmp_path / "scan.json"
    report.write_text(json.dumps(_medium_report()), encoding="utf-8")
    assert gate.main([str(report)]) == 1


def test_gate_medium_without_card_warns_with_flag(tmp_path):
    report = tmp_path / "scan.json"
    report.write_text(json.dumps(_medium_report()), encoding="utf-8")
    assert gate.main([str(report), "--warn-medium-without-card"]) == 0


def test_gate_high_still_fails_with_warn_flag(tmp_path):
    report = tmp_path / "scan.json"
    report.write_text(json.dumps({"risk_assessment": {"score": 60}}), encoding="utf-8")
    # The relaxation only covers MEDIUM; HIGH still fails.
    assert gate.main([str(report), "--warn-medium-without-card"]) == 1
