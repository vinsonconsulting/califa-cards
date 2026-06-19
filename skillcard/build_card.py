"""build_card.py -- assemble and validate a card (v2 stub).

SPEC.md section C: assembles the discover context plus scan, metrics, and
human-authored fields into a card; validates it against
:class:`schema.schema.SkillCard` (refusing on missing or mistyped required
fields); and writes ``skill-card.md`` plus the derived ``card.json``.

Not implemented in v0. The schema it will validate against already exists at
``schema/schema.py``. See SPEC.md sections C and H.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_card(context: dict[str, Any], out_dir: str | Path) -> None:
    raise NotImplementedError(
        "skillcard.build_card is a v2 stub (see SPEC.md sections C and H)"
    )
