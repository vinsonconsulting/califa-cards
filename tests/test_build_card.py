"""build_card tests: validate, serialize the canonical card.json, render its view."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schema.schema import SkillCard
from skillcard.build_card import BuildError, build_card

REPO = Path(__file__).resolve().parents[1]
TEXTUAL_JSON = REPO / "examples" / "textual" / "card.json"


def _card() -> dict:
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def test_writes_canonical_card_json_and_view(tmp_path):
    build_card(_card(), tmp_path)
    js = SkillCard.model_validate(json.loads((tmp_path / "card.json").read_text()))
    assert js.name == "textual"  # card.json is the canonical payload
    md = (tmp_path / "skill-card.md").read_text(encoding="utf-8")
    assert md.startswith("---\n")  # the view: readable-YAML frontmatter + body
    assert "# textual <small>v1.2.0</small>" in md


def test_card_json_is_canonical_and_newline_terminated(tmp_path):
    build_card(_card(), tmp_path)
    text = (tmp_path / "card.json").read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert '  "name": "textual"' in text  # 2-space indent
    # null optionals are emitted explicitly (matches the cabinet serializer).
    assert '"homepage": null' in text


def test_is_idempotent(tmp_path):
    build_card(_card(), tmp_path)
    first_md = (tmp_path / "skill-card.md").read_bytes()
    first_json = (tmp_path / "card.json").read_bytes()
    build_card(_card(), tmp_path)
    assert (tmp_path / "skill-card.md").read_bytes() == first_md
    assert (tmp_path / "card.json").read_bytes() == first_json


def test_refuses_missing_required_field_naming_it(tmp_path):
    card = _card()
    del card["permissions"]
    with pytest.raises(BuildError, match="permissions"):
        build_card(card, tmp_path)
    assert not (tmp_path / "card.json").exists()  # nothing written on refusal


def test_refuses_mistyped_field_naming_it(tmp_path):
    card = _card()
    card["scan"]["score"] = 142  # out of 0-100 range
    with pytest.raises(BuildError, match="score"):
        build_card(card, tmp_path)


def test_beta_card_serializes_metrics_null(tmp_path):
    card = _card()
    card["status"] = "beta"
    card["metrics"] = None
    build_card(card, tmp_path)
    data = json.loads((tmp_path / "card.json").read_text())
    assert data["metrics"] is None
    assert "## Quality scorecard" not in (tmp_path / "skill-card.md").read_text()
