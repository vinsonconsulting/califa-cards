"""review.py -- the inferred-vs-HUMAN sign-off gate (SPEC.md section C).

A generated card mixes machine-inferred fields (provenance, scan score, measured
metrics) with author judgement calls (summary, triggers, permissions, status,
accepted findings, scorecard caveats). The judgement calls must be confirmed by
a human before merge.

``skillcard build`` writes/refreshes ``card-review.md`` -- a checklist of the
HUMAN fields, each ``- [ ]`` until ticked ``- [x]``. The file records a
``fingerprint`` of card.json, so re-running build on an *unchanged* card keeps
the ticks (idempotent), while any change to the card resets the sign-off.

``skillcard review`` (and ``make check``) is a read-only gate: it returns
non-zero while any HUMAN row is un-ticked or the card has changed since review.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REVIEW_FILE = "card-review.md"
CARD_FILE = "card.json"

# Authored fields that always need sign-off when present (mirrors
# discover.HUMAN_FIELDS, but applied to the finished card).
_HUMAN_FIELDS = (
    "summary",
    "triggers",
    "inputs",
    "output",
    "dependencies",
    "external_endpoints",
    "permissions",
    "status",
)

_ROW_RE = re.compile(r"^- \[( |x)\]\s+`?(?P<key>[^`\s]+)`?")
_FINGERPRINT_RE = re.compile(r"^fingerprint:\s*(?P<fp>\S+)", re.MULTILINE)


@dataclass(frozen=True)
class Row:
    key: str
    note: str


def human_rows(card: dict[str, Any]) -> list[Row]:
    """The fields in a finished card that need human sign-off, in a stable order."""
    rows: list[Row] = []
    for field in _HUMAN_FIELDS:
        value = card.get(field)
        if value is None:
            continue
        rows.append(Row(field, _summarize(field, value)))
    for finding in (card.get("scan") or {}).get("findings", []) or []:
        if finding.get("status") == "accepted":
            rid = finding.get("rule_id", "?")
            rows.append(Row(f"scan.findings[{rid}]", f'accepted: "{finding.get("note") or ""}"'))
    metrics = card.get("metrics") or {}
    if metrics.get("notes"):
        rows.append(Row("metrics.notes", metrics["notes"]))
    return rows


def _summarize(field: str, value: Any) -> str:
    if field == "triggers":
        pos, neg = len(value.get("positive", [])), len(value.get("negative", []))
        return f"{pos} positive / {neg} negative"
    if field == "permissions":
        return " ".join(f"{k}={str(v).lower()}" for k, v in value.items())
    if isinstance(value, (list, dict)):
        return str(value)
    return str(value)


def fingerprint(card_json_text: str) -> str:
    return "sha256:" + hashlib.sha256(card_json_text.encode("utf-8")).hexdigest()


def _parse_existing(text: str) -> tuple[str | None, dict[str, bool]]:
    fp_match = _FINGERPRINT_RE.search(text)
    ticks: dict[str, bool] = {}
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m:
            ticks[m.group("key")] = m.group(1) == "x"
    return (fp_match.group("fp") if fp_match else None), ticks


def write_review(skill_dir: str | Path) -> None:
    """Create or refresh ``card-review.md`` for a built skill dir.

    Preserves the existing tick state for each row when the card.json fingerprint
    is unchanged; otherwise resets every row to un-ticked.
    """
    skill_dir = Path(skill_dir)
    import json  # noqa: PLC0415

    card_text = (skill_dir / CARD_FILE).read_text(encoding="utf-8")
    card = json.loads(card_text)
    fp = fingerprint(card_text)

    prior_ticks: dict[str, bool] = {}
    review_path = skill_dir / REVIEW_FILE
    if review_path.exists():
        old_fp, ticks = _parse_existing(review_path.read_text(encoding="utf-8"))
        if old_fp == fp:
            prior_ticks = ticks

    rows = human_rows(card)
    lines = [
        f"# Skill card review — {card.get('name', '?')}",
        "",
        "Each HUMAN field below needs sign-off: put an x in its checkbox once you",
        "have verified it. `skillcard review` / `make check` blocks until every box",
        "is checked. Regenerating the card with changed content resets this checklist.",
        "",
        f"fingerprint: {fp}",
        "",
    ]
    for row in rows:
        mark = "x" if prior_ticks.get(row.key) else " "
        lines.append(f"- [{mark}] `{row.key}` — {row.note}")
    lines.append("")
    review_path.write_text("\n".join(lines), encoding="utf-8")


def check(skill_dir: str | Path) -> tuple[int, list[str]]:
    """Read-only gate. Returns (exit_code, reasons)."""
    skill_dir = Path(skill_dir)
    review_path = skill_dir / REVIEW_FILE
    card_path = skill_dir / CARD_FILE
    if not card_path.exists():
        return 1, [f"{skill_dir}: no {CARD_FILE} to review"]
    if not review_path.exists():
        return 1, [f"{skill_dir}: no {REVIEW_FILE} (run `skillcard build` first)"]

    fp_now = fingerprint(card_path.read_text(encoding="utf-8"))
    old_fp, ticks = _parse_existing(review_path.read_text(encoding="utf-8"))
    if old_fp != fp_now:
        return 1, [
            f"{skill_dir}: card.json changed since review; re-verify and re-tick {REVIEW_FILE}"
        ]

    unticked = [key for key, ticked in ticks.items() if not ticked]
    if unticked:
        return 1, [f"{skill_dir}: un-ticked HUMAN field(s): {', '.join(unticked)}"]
    return 0, [f"{skill_dir}: all {len(ticks)} HUMAN field(s) signed off"]


def review(skill_dir: str | Path) -> int:
    """CLI entry: print the gate result, return its exit code."""
    code, reasons = check(skill_dir)
    head = "OK" if code == 0 else "FAIL"
    for reason in reasons:
        print(f"{head}: {reason}")
    return code
