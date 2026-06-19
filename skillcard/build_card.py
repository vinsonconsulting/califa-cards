"""build_card.py -- assemble, validate, and write a card (SPEC.md section C).

Takes the assembled card dict (from :mod:`skillcard.discover`), validates it
against :class:`schema.schema.SkillCard` -- refusing on any missing or mistyped
required field, naming it -- then writes both views so they agree 1:1:

* ``card.json``     -- canonical machine payload: ``json.dumps(model_dump(json),
                       indent=2)`` with all null-optionals emitted, schema order.
* ``skill-card.md`` -- the rendered human view (frontmatter + body).

As a backstop, the rendered frontmatter is parsed back and compared to the
validated card; a mismatch (a template defect) is a refusal, never a silent
divergence. The whole thing is a pure function of its input, so re-running on an
unchanged skill yields byte-identical output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from schema.schema import SkillCard
from skillcard.cli import parse_frontmatter
from skillcard.render import render


class BuildError(Exception):
    """A card could not be built: a required field is missing/mistyped, or the
    rendered md and card.json disagree."""


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["card validation failed; fix these fields:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def build_card(card: dict[str, Any], out_dir: str | Path) -> SkillCard:
    try:
        validated = SkillCard.model_validate(card)
    except ValidationError as exc:
        raise BuildError(_format_validation_error(exc)) from exc

    data = validated.model_dump(mode="json")
    card_json = json.dumps(data, indent=2) + "\n"
    md = render(data)

    # Backstop: the frontmatter must round-trip to the same card as card.json.
    reparsed = SkillCard.model_validate(parse_frontmatter(md))
    if reparsed.model_dump() != validated.model_dump():
        raise BuildError(
            "rendered skill-card.md frontmatter does not match card.json "
            "(template defect): the two views must agree 1:1"
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "card.json").write_text(card_json, encoding="utf-8")
    (out / "skill-card.md").write_text(md, encoding="utf-8")
    return validated
