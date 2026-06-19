"""The deterministic acceptance proof (SPEC.md section C, plan §Validate).

Regenerating the committed examples/textual card from its source inputs must
reproduce card.json and skill-card.md byte for byte. This is the in-repo
regression gate for the generator.
"""

from __future__ import annotations

from pathlib import Path

from skillcard import cli, review

REPO = Path(__file__).resolve().parents[1]
TEXTUAL = REPO / "examples" / "textual"


def test_examples_textual_regenerates_byte_for_byte(tmp_path):
    # Build from the real source dir, writing outputs into a scratch dir.
    cli.main(["build", str(TEXTUAL), "-o", str(tmp_path)])
    assert (tmp_path / "card.json").read_bytes() == (TEXTUAL / "card.json").read_bytes()
    assert (tmp_path / "skill-card.md").read_bytes() == (TEXTUAL / "skill-card.md").read_bytes()


def test_committed_example_passes_its_own_review_gate():
    # The committed checklist is fully signed off, so make check stays green.
    code, reasons = review.check(TEXTUAL)
    assert code == 0, reasons
