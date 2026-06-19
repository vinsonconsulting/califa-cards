"""The ``skillcard`` command-line entrypoint (SPEC.md section C).

Subcommands:

* ``validate``  validate a card against :class:`schema.schema.SkillCard`. Given a
                skill *directory* it runs the full provenance check: schema +
                skill-card.md/card.json agreement + ``content_hash``. Given a lone
                ``.md``/``.json`` file it schema-checks that file only.
* ``gate``      apply the SkillSpector score gate to a JSON report. Functional;
                delegates to :mod:`skillcard.gate`.
* ``hash``      compute the ``content_hash`` for a skill directory.
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
from skillcard.hashing import content_hash


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the leading YAML frontmatter of a skill-card.md *string* into a dict.

    Frontmatter is the block delimited by a leading ``---`` line and the next
    ``---`` line. Shared by the file loader below and by ``build_card``'s
    md/json agreement check. PyYAML is imported lazily so callers that only
    touch card.json never need it installed.
    """

    import yaml  # noqa: PLC0415

    if not text.startswith("---"):
        raise ValueError("no YAML frontmatter (text does not start with '---')")
    # Split into ['', frontmatter, body...]; the first chunk is empty.
    parts = text.split("\n---", 1)
    front = parts[0][len("---"):]
    block = front.split("\n", 1)[1] if "\n" in front else front
    data = yaml.safe_load(block)
    if not isinstance(data, dict):
        raise ValueError("frontmatter did not parse to a mapping")
    return data


def load_card_md(path: str) -> dict[str, Any]:
    """Parse the YAML frontmatter of a skill-card.md file into a dict."""

    try:
        return parse_frontmatter(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def load_card(path: str) -> dict[str, Any]:
    if path.endswith(".json"):
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if path.endswith((".md", ".markdown")):
        return load_card_md(path)
    raise ValueError(f"{path}: expected a .json or .md card")


def _cmd_validate(path: str) -> int:
    """Validate a card.

    A *directory* gets the full provenance check: validate skill-card.md and
    card.json against the schema, assert they agree 1:1, and verify the declared
    ``content_hash`` against the skill's source files. A lone ``.md``/``.json``
    file is schema-checked only (backward compatible).
    """

    p = Path(path)
    if p.is_dir():
        return _validate_skill_dir(p)
    data = load_card(path)
    SkillCard.model_validate(data)
    print(f"OK: {path} is a valid skill card (card_version {data.get('card_version')})")
    return 0


def _validate_skill_dir(skill_dir: Path) -> int:
    md_path = skill_dir / "skill-card.md"
    json_path = skill_dir / "card.json"
    present = [p for p in (md_path, json_path) if p.exists()]
    if not present:
        raise ValueError(f"{skill_dir}: no skill-card.md or card.json to validate")

    cards: dict[str, SkillCard] = {}
    for p in present:
        data = load_card(str(p))
        cards[p.name] = SkillCard.model_validate(data)
        print(f"OK: {p} validates (card_version {data.get('card_version')})")

    if md_path.name in cards and json_path.name in cards:
        if cards[md_path.name].model_dump() != cards[json_path.name].model_dump():
            print(f"FAIL: {skill_dir}: skill-card.md and card.json disagree (must be 1:1)")
            return 1
        print(f"OK: {md_path.name} and {json_path.name} agree")

    actual = content_hash(skill_dir)
    mismatched = {
        name: card.content_hash for name, card in cards.items() if card.content_hash != actual
    }
    if mismatched:
        print(
            f"FAIL: {skill_dir}: content_hash mismatch — recomputed {actual}, "
            f"card declares {mismatched}"
        )
        return 1
    print(f"OK: content_hash matches ({actual})")
    return 0


def _cmd_hash(skill_dir: str) -> int:
    print(content_hash(Path(skill_dir)))
    return 0


def _cmd_gate(report: str, card: str | None, warn_medium_without_card: bool) -> int:
    argv = [report]
    if card:
        argv += ["--card", card]
    if warn_medium_without_card:
        argv.append("--warn-medium-without-card")
    return gate.main(argv)


def _cmd_build(skill_dir: str, report: str | None, out: str | None) -> int:
    """Generate a card from a skill directory, then refresh its review checklist.

    Exits per the review gate: a freshly generated card has un-ticked HUMAN
    fields, so build flags that sign-off is still owed (non-zero) until a human
    ticks card-review.md.
    """

    from skillcard import review as rv  # noqa: PLC0415
    from skillcard.build_card import BuildError, build_card  # noqa: PLC0415
    from skillcard.discover import discover  # noqa: PLC0415

    out_dir = out or skill_dir
    try:
        result = discover(skill_dir, report_path=report)
        build_card(result.card, out_dir)
    except (BuildError, FileNotFoundError, ValueError) as exc:
        # The skill is not ready: a missing input file, or a missing/mistyped
        # required field. Report it cleanly rather than crashing.
        print(f"FAIL: {exc}")
        return 1

    rv.write_review(out_dir)
    inferred = sum(1 for v in result.provenance.values() if v == "inferred")
    human = sum(1 for v in result.provenance.values() if v == "human")
    print(f"OK: wrote {out_dir}/card.json and {out_dir}/skill-card.md")
    print(f"  {inferred} inferred field(s); {human} HUMAN field group(s) need sign-off")

    code, reasons = rv.check(out_dir)
    head = "OK" if code == 0 else "ACTION"
    for reason in reasons:
        print(f"{head}: {reason}")
    return code


def _cmd_review(skill_dir: str) -> int:
    from skillcard import review as rv  # noqa: PLC0415

    return rv.review(skill_dir)


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

    v = sub.add_parser(
        "validate", help="validate a card.json, skill-card.md, or a skill directory"
    )
    v.add_argument("path", help="a skill directory (full check) or a single card file")

    g = sub.add_parser("gate", help="apply the security gate to a SkillSpector JSON report")
    g.add_argument("report")
    g.add_argument("--card", default=None)
    g.add_argument(
        "--warn-medium-without-card",
        action="store_true",
        help="treat a MEDIUM band with no card as a warning (exit 0), not a failure; "
        "HIGH/CRITICAL and CRITICAL-severity findings still fail",
    )

    h = sub.add_parser("hash", help="compute the content_hash for a skill directory")
    h.add_argument("skill_dir")

    b = sub.add_parser("build", help="generate a card from a skill directory")
    b.add_argument("skill_dir")
    b.add_argument(
        "--report",
        default=None,
        help="SkillSpector JSON report (default: <skill_dir>/report.json or scan.json)",
    )
    b.add_argument("-o", "--out", default=None, help="output directory (default: the skill dir)")

    r = sub.add_parser(
        "review", help="gate: block until HUMAN-authored fields are signed off in card-review.md"
    )
    r.add_argument("skill_dir")

    sub.add_parser("badges", help="(v2) emit shields.io endpoint JSON from a card")

    args = parser.parse_args(argv)
    if args.cmd == "validate":
        return _cmd_validate(args.path)
    if args.cmd == "gate":
        return _cmd_gate(args.report, args.card, args.warn_medium_without_card)
    if args.cmd == "hash":
        return _cmd_hash(args.skill_dir)
    if args.cmd == "build":
        return _cmd_build(args.skill_dir, args.report, args.out)
    if args.cmd == "review":
        return _cmd_review(args.skill_dir)
    return _cmd_stub(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
