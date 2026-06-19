"""review.py -- inferred vs human-authored field review gate (v2 stub).

SPEC.md section C: presents a table of inferred versus human-authored fields
and blocks merge until each is ticked, so a generated card is never shipped
without a human confirming the judgement calls.

Not implemented in v0. See SPEC.md sections C and H.
"""

from __future__ import annotations

from typing import Any


def review(card: dict[str, Any]) -> bool:
    raise NotImplementedError(
        "skillcard.review is a v2 stub (see SPEC.md sections C and H)"
    )
