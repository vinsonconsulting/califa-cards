"""Badge generator tests (SPEC.md section F).

Every served shields endpoint must return HTTP 200, so the generator's contract
is "always a valid badge dict": metrics-absent (beta) cards yield a neutral grey
"n/a" badge for the numeric metrics and never raise. These tests cover all five
badge types across both a metrics-present card (the textual fixture) and a
synthesised metrics-absent (beta) variant, the shields shape, the colour-band
boundaries, the unknown-metric guard, and the CLI surface (stdout, --out, the
skill-dir write guard, and the missing-card path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillcard import badges, cli

REPO = Path(__file__).resolve().parents[1]
TEXTUAL = REPO / "examples" / "textual"
TEXTUAL_JSON = TEXTUAL / "card.json"

FIVE = {"scan", "trigger", "tasks", "signed", "card"}
REQUIRED_KEYS = {"schemaVersion", "label", "message", "color"}


def _stable_card() -> dict:
    """The committed textual card: stable, with a full metrics block."""
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def _beta_card() -> dict:
    """A metrics-absent variant: a beta card may omit the whole metrics block."""
    card = _stable_card()
    card.pop("metrics", None)
    card["status"] = "beta"
    return card


def _with_trigger(precision: float, recall: float) -> dict:
    card = _stable_card()
    card["metrics"]["trigger_precision"] = precision
    card["metrics"]["trigger_recall"] = recall
    return card


def _with_completion(rate: float) -> dict:
    card = _stable_card()
    card["metrics"]["task_completion_rate"] = rate
    return card


# --- shape / contract --------------------------------------------------------

def test_all_badges_returns_exactly_the_five_metrics():
    assert set(badges.all_badges(_stable_card())) == FIVE


def test_every_badge_has_the_shields_shape():
    card = _stable_card()
    for metric in FIVE:
        b = badges.badge(card, metric)
        assert set(b) == REQUIRED_KEYS
        assert b["schemaVersion"] == 1
        # JSON-serialisable and round-trips unchanged (it must serve as JSON).
        assert json.loads(json.dumps(b)) == b


# --- metrics present (the stable textual fixture) ----------------------------

def test_scan_badge_low_severity_is_brightgreen():
    b = badges.badge(_stable_card(), "scan")
    assert b["label"] == "scan"
    assert b["message"] == "LOW"
    assert b["color"] == "brightgreen"


def test_trigger_badge_shows_both_and_colours_on_average():
    b = badges.badge(_stable_card(), "trigger")
    assert b["label"] == "trigger"
    assert b["message"] == "P 0.95 / R 0.88"
    # avg(0.95, 0.88) = 0.915 >= 0.90 -> brightgreen
    assert b["color"] == "brightgreen"


def test_tasks_badge_is_percent_of_completion_rate():
    b = badges.badge(_stable_card(), "tasks")
    assert b["label"] == "tasks"
    assert b["message"] == "83%"
    # 0.83 in [0.80, 0.90) -> green
    assert b["color"] == "green"


def test_signed_badge_is_hash_tag_when_unsigned():
    b = badges.badge(_stable_card(), "signed")
    assert b["label"] == "signed"
    assert b["message"] == "hash+tag"
    assert b["color"] == "blue"


def test_signed_badge_is_oms_when_signature_present():
    card = _stable_card()
    card["signature"] = {"path": "sig.json", "cert": None}
    b = badges.badge(card, "signed")
    assert b["message"] == "oms"
    assert b["color"] == "blue"


def test_card_badge_carries_card_version():
    b = badges.badge(_stable_card(), "card")
    assert b["label"] == "card"
    assert b["message"] == "1.0"
    assert b["color"] == "informational"


# --- metrics absent (synthesised beta variant) -------------------------------

def test_trigger_badge_is_neutral_without_metrics():
    b = badges.badge(_beta_card(), "trigger")
    assert b["label"] == "trigger"
    assert b["message"] == "n/a"
    assert b["color"] == "lightgrey"


def test_tasks_badge_is_neutral_without_metrics():
    b = badges.badge(_beta_card(), "tasks")
    assert b["label"] == "tasks"
    assert b["message"] == "n/a"
    assert b["color"] == "lightgrey"


def test_scan_signed_card_are_real_without_metrics():
    card = _beta_card()
    assert badges.badge(card, "scan")["message"] == "LOW"
    assert badges.badge(card, "signed")["message"] == "hash+tag"
    assert badges.badge(card, "card")["message"] == "1.0"


def test_all_badges_never_raises_without_metrics():
    out = badges.all_badges(_beta_card())
    assert set(out) == FIVE
    assert out["trigger"]["message"] == "n/a"
    assert out["tasks"]["message"] == "n/a"


# --- colour-band boundaries (inclusive floor; first floor <= value wins) -----

@pytest.mark.parametrize(
    "value, color",
    [
        (0.90, "brightgreen"),
        (0.8999, "green"),
        (0.80, "green"),
        (0.7999, "yellowgreen"),
        (0.70, "yellowgreen"),
        (0.6999, "yellow"),
        (0.60, "yellow"),
        (0.5999, "orange"),
        (0.0, "orange"),
    ],
)
def test_trigger_band_boundaries(value, color):
    # precision == recall == value makes the colour-driving average exactly value.
    assert badges.badge(_with_trigger(value, value), "trigger")["color"] == color


@pytest.mark.parametrize(
    "value, color",
    [
        (0.90, "brightgreen"),
        (0.8999, "green"),
        (0.80, "green"),
        (0.7999, "yellowgreen"),
        (0.70, "yellowgreen"),
        (0.6999, "yellow"),
        (0.60, "yellow"),
        (0.5999, "orange"),
        (0.0, "orange"),
    ],
)
def test_tasks_band_boundaries(value, color):
    assert badges.badge(_with_completion(value), "tasks")["color"] == color


# --- unknown metric ----------------------------------------------------------

def test_unknown_metric_raises_value_error():
    with pytest.raises(ValueError):
        badges.badge(_stable_card(), "bogus")


# --- CLI ---------------------------------------------------------------------

def test_cli_badges_all_to_stdout(capsys):
    rc = cli.main(["badges", str(TEXTUAL), "--metric", "all"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == FIVE
    for b in payload.values():
        assert set(b) == REQUIRED_KEYS
        assert b["schemaVersion"] == 1


def test_cli_badges_default_metric_is_all(capsys):
    rc = cli.main(["badges", str(TEXTUAL)])
    assert rc == 0
    assert set(json.loads(capsys.readouterr().out)) == FIVE


def test_cli_badges_single_metric_to_stdout(capsys):
    rc = cli.main(["badges", str(TEXTUAL), "--metric", "scan"])
    assert rc == 0
    b = json.loads(capsys.readouterr().out)
    assert b["label"] == "scan"
    assert b["message"] == "LOW"


def test_cli_badges_out_dir_writes_one_file_per_badge(tmp_path):
    out_dir = tmp_path / "badges"
    rc = cli.main(["badges", str(TEXTUAL), "--metric", "all", "--out", str(out_dir)])
    assert rc == 0
    for metric in FIVE:
        f = out_dir / f"{metric}.json"
        assert f.exists()
        b = json.loads(f.read_text(encoding="utf-8"))
        assert set(b) == REQUIRED_KEYS
        assert b["schemaVersion"] == 1


def test_cli_badges_out_single_metric_writes_one_file(tmp_path):
    out_dir = tmp_path / "badges"
    rc = cli.main(["badges", str(TEXTUAL), "--metric", "tasks", "--out", str(out_dir)])
    assert rc == 0
    assert (out_dir / "tasks.json").exists()
    assert not (out_dir / "scan.json").exists()


def test_cli_badges_refuses_out_into_skill_dir(tmp_path):
    # Writing badge files into the skill dir would move its content_hash (and a
    # card.json badge would clobber the manifest), so it must be refused.
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "card.json").write_text(TEXTUAL_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    rc = cli.main(["badges", str(skill), "--metric", "all", "--out", str(skill)])
    assert rc == 1
    assert not (skill / "trigger.json").exists()
    assert not (skill / "scan.json").exists()


def test_cli_badges_refuses_out_nested_in_skill_dir(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "card.json").write_text(TEXTUAL_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    nested = skill / "badges"
    rc = cli.main(["badges", str(skill), "--out", str(nested)])
    assert rc == 1
    assert not nested.exists()


def test_cli_badges_missing_card_json_fails(tmp_path):
    assert cli.main(["badges", str(tmp_path)]) == 1
