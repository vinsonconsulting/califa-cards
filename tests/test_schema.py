"""Schema tests: the textual example validates; bad cards are rejected."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from schema.schema import SkillCard

REPO = Path(__file__).resolve().parents[1]
CARD_JSON = REPO / "examples" / "textual" / "card.json"


def _valid_dict() -> dict:
    return json.loads(CARD_JSON.read_text(encoding="utf-8"))


def test_textual_card_json_is_valid():
    card = SkillCard.model_validate(_valid_dict())
    assert card.name == "textual"
    assert card.scan.severity == "LOW"
    assert card.external_endpoints == "none"


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


def test_metrics_notes_is_optional_and_roundtrips():
    # The one additive v2 field: a nullable caveat home (e.g. the github-readme
    # recall triage) so caveats live structurally instead of as body prose.
    data = _valid_dict()
    data["metrics"]["notes"] = "trigger_recall is a harness-floor artifact, not a capability signal"
    card = SkillCard.model_validate(data)
    assert card.metrics.notes == data["metrics"]["notes"]
    # Absent → None, and not invented on dump.
    data["metrics"].pop("notes")
    assert SkillCard.model_validate(data).metrics.notes is None
