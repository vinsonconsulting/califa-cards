"""Render tests: the Jinja template is a pure, round-tripping function of a card.

The frontmatter the template emits is the canonical machine payload, so parsing
it back must reproduce the card exactly (the md/json 1:1 contract). The body is
the human view: deterministic sections derived only from card fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from schema.schema import SkillCard
from skillcard.cli import parse_frontmatter
from skillcard.render import render

REPO = Path(__file__).resolve().parents[1]
TEXTUAL_JSON = REPO / "examples" / "textual" / "card.json"


def _card() -> dict:
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def _roundtrip(card: dict) -> dict:
    """Render, then parse the frontmatter back to a validated model_dump."""
    md = render(card)
    front = parse_frontmatter(md)
    return SkillCard.model_validate(front).model_dump()


def test_frontmatter_roundtrips_one_to_one():
    card = _card()
    assert _roundtrip(card) == SkillCard.model_validate(card).model_dump()


def test_body_has_deterministic_sections():
    md = render(_card())
    assert "# textual" in md
    assert "## When to use it" in md
    assert "## Quality scorecard" in md
    assert "Near-miss precision" in md  # the row v1's template dropped
    assert "## Security" in md
    assert "skillspector@a5092dd" in md  # security section derives from scan.tool


def test_null_finding_fields_render_as_yaml_null():
    # owasp is null on the AST4 finding; it must round-trip to None, not "None".
    card = _card()
    front = parse_frontmatter(render(card))
    assert front["scan"]["findings"][0]["owasp"] is None
    assert front["scan"]["findings"][0]["atlas"] == "AML.T0050"


def test_metrics_notes_renders_when_present():
    card = _card()
    card["metrics"]["notes"] = "recall is a harness-floor artifact: not a capability signal"
    md = render(card)
    assert _roundtrip(card)["metrics"]["notes"] == card["metrics"]["notes"]
    assert "harness-floor artifact" in md  # surfaced as a body caveat too


def test_beta_path_omits_metrics_block_and_scorecard():
    card = _card()
    card["status"] = "beta"
    card["metrics"] = None
    md = render(card)
    front = parse_frontmatter(md)
    assert front["metrics"] is None
    assert SkillCard.model_validate(front).metrics is None
    assert "## Quality scorecard" not in md  # no scorecard without metrics
    assert "## Security" in md  # scan is always present


def test_empty_findings_render_as_list_not_null():
    # A clean scan (score 0, no findings) must emit findings: [] so it validates.
    card = _card()
    card["scan"]["score"] = 0
    card["scan"]["severity"] = "LOW"
    card["scan"]["findings"] = []
    front = parse_frontmatter(render(card))
    assert front["scan"]["findings"] == []
