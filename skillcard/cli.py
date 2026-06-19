"""The ``skillcard`` command-line entrypoint (SPEC.md section C).

v0 subcommands:

* ``validate``  load a card.json or skill-card.md and validate it against
                :class:`schema.schema.SkillCard`. Functional.
* ``gate``      apply the SkillSpector score gate to a JSON report. Functional;
                delegates to :mod:`skillcard.gate`.
* ``build``     (v2) generate a card from a skill directory. Stub.
* ``badges``    (v2) emit shields.io endpoint JSON from a card. Stub.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from schema.schema import SkillCard
from skillcard import gate


def load_card_md(path: str) -> dict[str, Any]:
    """Parse the YAML frontmatter of a skill-card.md into a dict.

    Frontmatter is the block delimited by a leading ``---`` line and the next
    ``---`` line. PyYAML is imported lazily so callers that only touch
    card.json never need it installed.
    """

    import yaml  # noqa: PLC0415

    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path}: no YAML frontmatter (file does not start with '---')")
    # Split into ['', frontmatter, body...]; the first chunk is empty.
    parts = text.split("\n---", 1)
    front = parts[0][len("---"):]
    block = front.split("\n", 1)[1] if "\n" in front else front
    data = yaml.safe_load(block)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: frontmatter did not parse to a mapping")
    return data


def load_card(path: str) -> dict[str, Any]:
    if path.endswith(".json"):
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if path.endswith((".md", ".markdown")):
        return load_card_md(path)
    raise ValueError(f"{path}: expected a .json or .md card")


def _cmd_validate(path: str) -> int:
    data = load_card(path)
    SkillCard.model_validate(data)
    print(f"OK: {path} is a valid skill card (card_version {data.get('card_version')})")
    return 0


def _cmd_gate(report: str, card: str | None) -> int:
    return gate.main([report] + (["--card", card] if card else []))


def _cmd_stub(name: str) -> int:
    print(
        f"skillcard {name}: not implemented in v0. Planned for v2 "
        f"(see SPEC.md sections C and H)."
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skillcard", description="Califa Cards skill-card tooling."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="validate a card.json or skill-card.md")
    v.add_argument("path")

    g = sub.add_parser("gate", help="apply the security gate to a SkillSpector JSON report")
    g.add_argument("report")
    g.add_argument("--card", default=None)

    sub.add_parser("build", help="(v2) generate a card from a skill directory")
    sub.add_parser("badges", help="(v2) emit shields.io endpoint JSON from a card")

    args = parser.parse_args(argv)
    if args.cmd == "validate":
        return _cmd_validate(args.path)
    if args.cmd == "gate":
        return _cmd_gate(args.report, args.card)
    return _cmd_stub(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
