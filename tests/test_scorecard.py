"""Scorecard renderer tests (skillcard.scorecard + the CLI surface).

The renderer's contract mirrors badges: it never raises on missing card data, so
a sparse beta card (no metrics block) degrades to a muted placeholder rather than
crashing, and output is deterministic so a committed SVG never churns. These
tests cover the colour-band boundaries, the full/sparse render paths, byte-for-byte
determinism, and the CLI (stdout, --out file, the skill-dir write guard, and the
missing-card path). Textual is the heavy ``scorecard`` extra, so the whole module
skips when it is not installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("textual", reason="needs the 'scorecard' extra (Textual)")

from skillcard import cli, scorecard  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TEXTUAL_JSON = REPO / "examples" / "textual" / "card.json"


def _stable_card() -> dict:
    """The committed textual card: stable, with a full metrics block."""
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def _beta_card() -> dict:
    """A metrics-absent variant: a beta card may omit the whole metrics block."""
    card = _stable_card()
    card.pop("metrics", None)
    card["status"] = "beta"
    return card


# --- colour bands ------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        (0.95, "green"),
        (0.90, "green"),
        (0.85, "chartreuse1"),
        (0.80, "chartreuse1"),
        (0.75, "yellow"),
        (0.70, "yellow"),
        (0.65, "gold1"),
        (0.60, "gold1"),
        (0.10, "red"),
        (0.0, "red"),
    ],
)
def test_numeric_band_boundaries(value: float, expected: str):
    assert scorecard._band_color(value, scorecard.THRESHOLDS["numeric"]) == expected


def test_security_cell_maps_severity_to_colour():
    msg, color = scorecard._security_cell(_stable_card())
    assert msg == "12 / LOW"
    assert color == scorecard.THRESHOLDS["severity"]["LOW"]


def test_security_cell_is_neutral_without_scan():
    msg, color = scorecard._security_cell({})
    assert msg == "n/a"
    assert color == scorecard.NA


def test_provenance_prefers_harness_then_falls_back_to_scan():
    assert scorecard._provenance(_stable_card()).startswith("harness  ")
    assert scorecard._provenance(_beta_card()).startswith("scan  ")


# --- render paths ------------------------------------------------------------

def test_full_card_renders_an_svg():
    svg = scorecard.render_card(_stable_card())
    assert "<svg" in svg and "</svg>" in svg
    assert len(svg) > 1000


def test_sparse_beta_card_renders_without_error():
    # The common case: no metrics block. Must degrade, not crash.
    svg = scorecard.render_card(_beta_card())
    assert "<svg" in svg and "</svg>" in svg


def test_render_is_deterministic():
    card = _stable_card()
    assert scorecard.render_card(card) == scorecard.render_card(card)


def test_near_miss_is_omitted_when_absent():
    # Dropping near_miss_precision must not raise (it is an optional row).
    card = _stable_card()
    card["metrics"]["near_miss_precision"] = None
    assert "<svg" in scorecard.render_card(card)


# --- rollup ------------------------------------------------------------------

def _summary() -> dict:
    return {
        "title": "claude-skill-foundry",
        "total": 6,
        "carded": 4,
        "with_metrics": 1,
        "severity_counts": {"LOW": 3, "MEDIUM": 1, "HIGH": 0, "CRITICAL": 0},
        "worst": "MEDIUM",
    }


def test_rollup_renders_an_svg():
    svg = scorecard.render_rollup(_summary())
    assert "<svg" in svg and "</svg>" in svg


def test_rollup_is_deterministic():
    s = _summary()
    assert scorecard.render_rollup(s) == scorecard.render_rollup(s)


def test_rollup_degrades_on_empty_corpus():
    # Nothing carded yet: still a valid SVG, not a crash.
    empty = {"title": "x", "total": 0, "carded": 0, "with_metrics": 0,
             "severity_counts": {}, "worst": None}
    assert "<svg" in scorecard.render_rollup(empty)


# --- CLI surface -------------------------------------------------------------

def test_cli_writes_svg_to_stdout(capsys):
    rc = cli.main(["scorecard", str(TEXTUAL_JSON.parent), "--out", "-"])
    assert rc == 0
    assert "<svg" in capsys.readouterr().out


def test_cli_writes_svg_to_file(tmp_path):
    out = tmp_path / "sub" / "scorecard.svg"
    rc = cli.main(["scorecard", str(TEXTUAL_JSON.parent), "--out", str(out)])
    assert rc == 0
    assert "<svg" in out.read_text(encoding="utf-8")


def test_cli_refuses_out_inside_skill_dir(capsys):
    skill = TEXTUAL_JSON.parent
    rc = cli.main(["scorecard", str(skill), "--out", str(skill / "scorecard.svg")])
    assert rc == 1
    assert "content_hash" in capsys.readouterr().out


def test_cli_reports_missing_card(tmp_path, capsys):
    rc = cli.main(["scorecard", str(tmp_path), "--out", "-"])
    assert rc == 1
    assert "no card.json" in capsys.readouterr().out
