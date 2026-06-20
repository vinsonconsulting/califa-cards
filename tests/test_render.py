"""Render tests: the template is a deterministic, one-way function of a card.

skill-card.md is a *view* of card.json, not a second source: ``json -> md`` is
deterministic (guarded byte-for-byte by test_examples), but the md is never
parsed back, so there is no md/json parity contract. The frontmatter is readable
YAML; the body is deterministic sections derived only from card fields. The
parses below are convenience spot-checks on specific values, not parity asserts.
"""

from __future__ import annotations

import json
from pathlib import Path

from skillcard.cli import parse_frontmatter
from skillcard.render import render

REPO = Path(__file__).resolve().parents[1]
TEXTUAL_JSON = REPO / "examples" / "textual" / "card.json"


def _card() -> dict:
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def _front(card: dict) -> dict:
    """Parse the rendered frontmatter back to a dict (for value spot-checks)."""
    return parse_frontmatter(render(card))


def test_frontmatter_is_readable_yaml_not_json_leaves():
    # The JSON-leaf encoding is gone: collections render as block-style YAML, not
    # inline JSON objects. permissions is a nested mapping in the frontmatter.
    md = render(_card())
    front, _ = md.split("\n---", 1)
    assert "permissions:\n" in front  # block mapping, with children on their own lines
    assert "  network: false" in front
    assert '{ "' not in front and "{ network:" not in front  # no JSON / inline-flow leaves


def test_body_has_deterministic_sections():
    md = render(_card())
    assert "# textual" in md
    assert "## When to use it" in md
    assert "## Quality scorecard" in md
    assert "Near-miss precision" in md  # the row v1's template dropped
    assert "## Security" in md
    assert "skillspector@a5092dd" in md  # security section derives from scan.tool


def test_null_finding_fields_render_as_yaml_null():
    # owasp is null on the AST4 finding; it must render as YAML null, not "None".
    front = _front(_card())
    assert front["scan"]["findings"][0]["owasp"] is None
    assert front["scan"]["findings"][0]["atlas"] == "AML.T0050"


def test_metrics_notes_renders_in_frontmatter_and_body():
    card = _card()
    card["metrics"]["notes"] = "recall is a harness-floor artifact: not a capability signal"
    md = render(card)
    assert _front(card)["metrics"]["notes"] == card["metrics"]["notes"]
    assert "harness-floor artifact" in md  # surfaced as a body caveat too


def test_beta_path_omits_metrics_block_and_scorecard():
    card = _card()
    card["status"] = "beta"
    card["metrics"] = None
    md = render(card)
    assert _front(card)["metrics"] is None  # explicit `metrics: null` in the view
    assert "## Quality scorecard" not in md  # no scorecard without metrics
    assert "## Security" in md  # scan is always present


def test_empty_findings_render_as_list_not_null():
    # A clean scan (score 0, no findings) must emit findings: [] so it reads cleanly.
    card = _card()
    card["scan"]["score"] = 0
    card["scan"]["severity"] = "LOW"
    card["scan"]["findings"] = []
    assert _front(card)["scan"]["findings"] == []
