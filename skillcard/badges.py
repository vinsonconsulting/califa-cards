"""badges.py -- map a card to shields.io endpoint JSON (v2 stub).

SPEC.md section F: maps ``card.json`` to the shields.io endpoint payload
``{schemaVersion: 1, label, message, color}`` per metric (scan, trigger,
tasks, signed, card). One color-threshold config; every endpoint must return
HTTP 200. Reads directly from the card so there is no second source of truth.

Not implemented in v0; v1 README badges are static shields. See SPEC.md
sections F and H.
"""

from __future__ import annotations

from typing import Any


def badge(card: dict[str, Any], metric: str) -> dict[str, Any]:
    raise NotImplementedError(
        "skillcard.badges is a v2 stub (see SPEC.md sections F and H)"
    )
