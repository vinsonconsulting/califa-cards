"""discover.py -- walk a skill directory into a context dict (v2 stub).

SPEC.md section C: the first stage of the generator chain. Walks a skill
bundle (SKILL.md, references/, scripts/, assets/, evals/) and produces the
context dict that :mod:`skillcard.build_card` assembles into a card.

Not implemented in v0. See SPEC.md sections C and H.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def discover(skill_dir: str | Path) -> dict[str, Any]:
    raise NotImplementedError(
        "skillcard.discover is a v2 stub (see SPEC.md sections C and H)"
    )
