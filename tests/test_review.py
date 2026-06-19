"""Review-gate tests: HUMAN fields must be ticked, bound to the card's content."""

from __future__ import annotations

import json
from pathlib import Path

from skillcard import review as rv
from skillcard.build_card import build_card

REPO = Path(__file__).resolve().parents[1]
TEXTUAL_JSON = REPO / "examples" / "textual" / "card.json"


def _card() -> dict:
    return json.loads(TEXTUAL_JSON.read_text(encoding="utf-8"))


def _built(tmp_path) -> Path:
    """A built skill dir with a fresh (un-ticked) review file."""
    build_card(_card(), tmp_path)
    rv.write_review(tmp_path)
    return tmp_path


def _tick_all(skill_dir: Path) -> None:
    text = (skill_dir / "card-review.md").read_text(encoding="utf-8")
    (skill_dir / "card-review.md").write_text(text.replace("- [ ]", "- [x]"), encoding="utf-8")


def test_human_rows_cover_authored_and_accepted_findings():
    rows = {row.key for row in rv.human_rows(_card())}
    assert "summary" in rows
    assert "triggers" in rows
    assert "permissions" in rows
    assert "status" in rows
    assert "scan.findings[AST4]" in rows  # the accepted finding
    assert "name" not in rows  # inferred, no sign-off
    assert "content_hash" not in rows


def test_review_fails_while_unticked(tmp_path):
    _built(tmp_path)
    code, reasons = rv.check(tmp_path)
    assert code != 0
    assert any("summary" in r for r in reasons)


def test_review_passes_when_all_ticked(tmp_path):
    _built(tmp_path)
    _tick_all(tmp_path)
    code, _ = rv.check(tmp_path)
    assert code == 0


def test_ticks_are_invalidated_when_card_changes(tmp_path):
    _built(tmp_path)
    _tick_all(tmp_path)
    assert rv.check(tmp_path)[0] == 0
    # Mutate the card.json: the prior sign-off no longer applies.
    card = _card()
    card["summary"] = "a materially different summary"
    (tmp_path / "card.json").write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    code, reasons = rv.check(tmp_path)
    assert code != 0
    assert any("changed" in r.lower() for r in reasons)


def test_refresh_preserves_ticks_when_card_unchanged(tmp_path):
    _built(tmp_path)
    _tick_all(tmp_path)
    before = (tmp_path / "card-review.md").read_bytes()
    # Re-running build + write_review on the unchanged card must not drop ticks.
    build_card(_card(), tmp_path)
    rv.write_review(tmp_path)
    assert (tmp_path / "card-review.md").read_bytes() == before
    assert rv.check(tmp_path)[0] == 0


def test_missing_review_file_fails(tmp_path):
    build_card(_card(), tmp_path)  # no write_review
    code, reasons = rv.check(tmp_path)
    assert code != 0
    assert any("card-review.md" in r for r in reasons)
