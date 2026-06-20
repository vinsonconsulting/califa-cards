"""render.py -- render a card to skill-card.md (SPEC.md section C).

One-way and deterministic: a pure function of the card dict, with no I/O beyond
reading the body template. The frontmatter is emitted as **readable YAML** (via
``yaml.safe_dump``); the body is the Jinja-rendered human view.

skill-card.md is a *view*: ``card.json`` is the canonical machine payload, and the
md is never parsed back into a card. So the frontmatter optimizes for human
readability -- block-style collections, long scalars on one line, null-optionals
omitted -- rather than for the byte-exact round-tripping the old JSON-leaf
encoding guaranteed. ``json -> md`` stays deterministic (the byte-for-byte
fixture test guards it); ``md -> json`` parity is no longer a requirement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_NAME = "skill-card.md.j2"

# Metric fields that are dropped from the view when null, mirroring the body's
# "omit when absent" rule so the scorecard frontmatter stays uncluttered.
_OPTIONAL_METRICS = ("near_miss_precision", "tool_call_delta", "token_efficiency", "notes")


def _default_template_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "templates"


def _prune_metrics(metrics: dict[str, Any] | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    return {k: v for k, v in metrics.items() if not (k in _OPTIONAL_METRICS and v is None)}


def _frontmatter(card: dict[str, Any]) -> dict[str, Any]:
    """The card as an ordered, view-pruned frontmatter mapping (schema order).

    Required fields are always present; the three null-optionals the old template
    omitted (``homepage``, ``signature``, ``inputs``) are dropped when absent.
    ``metrics: null`` stays explicit so a beta card visibly has no scorecard yet.
    """
    fm: dict[str, Any] = {
        "name": card["name"],
        "version": card["version"],
        "summary": card["summary"],
        "owner": card["owner"],
        "repo": card["repo"],
        "license": card["license"],
    }
    if card.get("homepage") is not None:
        fm["homepage"] = card["homepage"]
    fm["source_commit"] = card["source_commit"]
    fm["content_hash"] = card["content_hash"]
    if card.get("signature") is not None:
        fm["signature"] = card["signature"]
    fm["description"] = card["description"]
    fm["triggers"] = card["triggers"]
    if card.get("inputs") is not None:
        fm["inputs"] = card["inputs"]
    fm["output"] = card["output"]
    fm["dependencies"] = card["dependencies"]
    fm["external_endpoints"] = card["external_endpoints"]
    fm["permissions"] = card["permissions"]
    fm["metrics"] = _prune_metrics(card.get("metrics"))
    fm["scan"] = card["scan"]
    fm["status"] = card["status"]
    fm["card_version"] = card["card_version"]
    fm["updated"] = card["updated"]
    return fm


def _dump_frontmatter(card: dict[str, Any]) -> str:
    # width=4096 keeps long scalars (description/summary) on one line; sort_keys
    # off preserves schema order; allow_unicode keeps em-dashes literal.
    return yaml.safe_dump(
        _frontmatter(card),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    )


def _render_body(card: dict[str, Any], template_dir: str | Path | None = None) -> str:
    tdir = Path(template_dir) if template_dir is not None else _default_template_dir()
    env = Environment(
        loader=FileSystemLoader(str(tdir)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(_TEMPLATE_NAME).render(card=card)


def render(card: dict[str, Any], template_dir: str | Path | None = None) -> str:
    """Render a card to skill-card.md: readable-YAML frontmatter + Jinja body."""
    return f"---\n{_dump_frontmatter(card)}---\n\n{_render_body(card, template_dir)}"
