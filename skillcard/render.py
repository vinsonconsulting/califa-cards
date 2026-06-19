"""render.py -- render a card to skill-card.md via Jinja (SPEC.md section C).

Pure function of the card dict: no side effects, no I/O beyond reading the
template. The frontmatter it emits is the canonical machine payload (parsed back
by :mod:`skillcard.build_card` to enforce md/json 1:1 agreement); the body is the
human view.

Every frontmatter leaf is rendered through the ``j`` filter, which JSON-encodes
the value. JSON is a subset of YAML, so the result is always valid YAML that
round-trips to the exact value -- this is what makes ``null``, booleans, numbers,
and strings containing colons or quotes safe without per-field quoting rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_NAME = "skill-card.md.j2"


def _default_template_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "templates"


def _yaml_scalar(value: Any) -> str:
    """JSON-encode a leaf so it is valid, round-tripping YAML.

    ``ensure_ascii=False`` keeps the human view readable (a literal ``—`` rather
    than ``\\u2014``); the value still parses back identically.
    """
    return json.dumps(value, ensure_ascii=False)


def render(card: dict[str, Any], template_dir: str | Path | None = None) -> str:
    tdir = Path(template_dir) if template_dir is not None else _default_template_dir()
    env = Environment(
        loader=FileSystemLoader(str(tdir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["j"] = _yaml_scalar
    return env.get_template(_TEMPLATE_NAME).render(card=card)
