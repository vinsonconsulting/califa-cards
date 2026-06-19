"""render.py -- render card.json to skill-card.md via Jinja (v2 stub).

SPEC.md section C: renders the machine card (``card.json``) through
``templates/skill-card.md.j2`` into the human view (``skill-card.md``). The
template already exists; this module will wire it to Jinja in v2.

Not implemented in v0. See SPEC.md sections C and H.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render(card: dict[str, Any], template_dir: str | Path | None = None) -> str:
    raise NotImplementedError(
        "skillcard.render is a v2 stub (see SPEC.md sections C and H)"
    )
