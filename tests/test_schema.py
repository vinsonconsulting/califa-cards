"""Schema tests: the textual example validates; bad cards are rejected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from schema.schema import SkillCard
from skillcard.cli import load_card

REPO = Path(__file__).resolve().parents[1]
CARD_JSON = REPO / "examples" / "textual" / "card.json"
CARD_MD = REPO / "examples" / "textual" / "skill-card.md"


def _valid_dict() -> dict:
    return json.loads(CARD_JSON.read_text(encoding="utf-8"))


def test_textual_card_json_is_valid():
    card = SkillCard.model_validate(_valid_dict())
    assert card.name == "textual"
    assert card.scan.severity == "LOW"
    assert card.external_endpoints == "none"


def test_textual_skill_card_md_frontmatter_is_valid():
    # The human-view frontmatter must validate against the same schema.
    data = load_card(str(CARD_MD))
    card = SkillCard.model_validate(data)
    assert card.name == "textual"


def test_md_and_json_agree():
    # card.json is derived 1:1 from the skill-card.md frontmatter.
    md = SkillCard.model_validate(load_card(str(CARD_MD)))
    js = SkillCard.model_validate(_valid_dict())
    assert md.model_dump() == js.model_dump()


def test_missing_required_field_rejected():
    data = _valid_dict()
    del data["name"]
    with pytest.raises(ValidationError):
        SkillCard.model_validate(data)


def test_unknown_field_rejected():
    data = _valid_dict()
    data["bogus_field"] = "nope"
    with pytest.raises(ValidationError):
        SkillCard.model_validate(data)


def test_bad_slug_rejected():
    data = _valid_dict()
    data["name"] = "Textual_App"  # uppercase and underscore: not a slug
    with pytest.raises(ValidationError):
        SkillCard.model_validate(data)


def test_score_out_of_range_rejected():
    data = _valid_dict()
    data["scan"]["score"] = 142
    with pytest.raises(ValidationError):
        SkillCard.model_validate(data)


def test_metric_out_of_range_rejected():
    data = _valid_dict()
    data["metrics"]["trigger_precision"] = 1.5
    with pytest.raises(ValidationError):
        SkillCard.model_validate(data)


def test_beta_card_without_metrics_is_valid():
    # Lifecycle refinement: non-stable cards may omit the metrics block.
    data = _valid_dict()
    del data["metrics"]
    data["status"] = "beta"
    card = SkillCard.model_validate(data)
    assert card.metrics is None


def test_stable_card_without_metrics_rejected():
    data = _valid_dict()
    del data["metrics"]
    data["status"] = "stable"
    with pytest.raises(ValidationError):
        SkillCard.model_validate(data)
