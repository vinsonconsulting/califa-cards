"""SkillSpector security gate (SPEC.md section E).

Why this reads JSON, not SARIF
-------------------------------
The spec originally assumed the 0-100 risk score lived in the SARIF report.
It does not. SkillSpector's SARIF result model is ``{ruleId, message, level,
locations}`` only: no score, no per-finding severity beyond a lossy ``level``
(CRITICAL and HIGH both collapse to ``"error"``), and the executable-scripts
multiplier is absent. The authoritative score and exact severities live in
SkillSpector's ``--format json`` report. So the gate reads JSON; SARIF is still
produced in CI for ``github/codeql-action/upload-sarif`` (the Security tab).

Policy
------
* score 0-20 (LOW band)            -> PASS
* score 21-50 (MEDIUM band)        -> PASS only if every finding is recorded on
                                      the card with ``status: accepted`` and a
                                      non-empty note. No blank overrides.
* score 51-100 (HIGH/CRITICAL)     -> hard FAIL
* any CRITICAL-severity finding    -> hard FAIL regardless of total score

The gate does not blanket-reject subprocess or shell patterns. A finding fails
only when it is un-accepted or un-noted, so a skill that legitimately runs, say,
``pytest`` passes once that is declared and justified in its card.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Score band edges (inclusive upper bound), highest band last.
_BANDS = [(20, "LOW"), (50, "MEDIUM"), (80, "HIGH"), (100, "CRITICAL")]

# Candidate JSON paths for the score and the findings list, tried in order.
# SkillSpector's JSON report nests the score under risk_assessment; the other
# keys are fallbacks so the gate tolerates output-shape drift.
_SCORE_PATHS = (
    ("risk_assessment", "score"),
    ("risk_score",),
    ("score",),
)
_FINDINGS_KEYS = ("issues", "findings", "filtered_findings")


@dataclass
class GateResult:
    passed: bool
    score: int
    band: str
    reasons: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        head = "PASS" if self.passed else "FAIL"
        lines = [f"[{head}] score={self.score} band={self.band}"]
        lines.extend(f"  - {r}" for r in self.reasons)
        return "\n".join(lines)


def _band(score: int) -> str:
    for edge, name in _BANDS:
        if score <= edge:
            return name
    return "CRITICAL"


def _dig(report: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = report
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def extract_score(report: dict[str, Any]) -> int:
    for path in _SCORE_PATHS:
        value = _dig(report, path)
        if isinstance(value, (int, float)):
            return int(value)
    raise ValueError(
        "could not find a risk score in the report "
        f"(looked at {', '.join('.'.join(p) for p in _SCORE_PATHS)})"
    )


def extract_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    for key in _FINDINGS_KEYS:
        value = report.get(key)
        if isinstance(value, list):
            return [f for f in value if isinstance(f, dict)]
    return []


def _severity(finding: dict[str, Any]) -> str:
    return str(finding.get("severity", "LOW")).upper()


def _rule_id(finding: dict[str, Any]) -> str:
    # SkillSpector's JSON report identifies each finding by ``id`` (e.g. "E1",
    # "LP3"); ``rule_id``/``ruleId`` are accepted too for forward-compatibility.
    return str(finding.get("rule_id") or finding.get("ruleId") or finding.get("id") or "")


def _card_findings_index(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scan = card.get("scan") or {}
    index: dict[str, dict[str, Any]] = {}
    for entry in scan.get("findings", []) or []:
        if isinstance(entry, dict):
            index[str(entry.get("rule_id", ""))] = entry
    return index


def evaluate(
    report: dict[str, Any],
    card: dict[str, Any] | None = None,
    warn_medium_without_card: bool = False,
) -> GateResult:
    """Apply the gate policy to a parsed SkillSpector JSON report.

    ``card`` is an optional parsed skill-card (the dict form of card.json). It
    supplies the ``status: accepted`` plus note annotations the MEDIUM band
    requires. A self-scan of a non-skill repo passes with ``card=None`` only
    when it lands in the LOW band.

    ``warn_medium_without_card`` relaxes one case: a MEDIUM-band scan with no
    card passes with a warning instead of failing. This lets a cabinet gate
    *every* skill on HIGH/CRITICAL while it incrementally cards the rest; the
    HIGH/CRITICAL and CRITICAL-severity rules are never relaxed.
    """

    score = extract_score(report)
    band = _band(score)
    findings = extract_findings(report)

    critical = [f for f in findings if _severity(f) == "CRITICAL"]
    if critical:
        ids = ", ".join(sorted({_rule_id(f) or "?" for f in critical}))
        return GateResult(False, score, band, [f"CRITICAL-severity finding(s): {ids}"])

    if band in ("HIGH", "CRITICAL"):
        return GateResult(False, score, band, [f"score {score} is in the {band} band (>=51)"])

    if band == "LOW":
        return GateResult(True, score, band, ["LOW band: pass"])

    # MEDIUM band: every finding must be accepted and noted on the card.
    if card is None:
        if warn_medium_without_card:
            return GateResult(
                True,
                score,
                band,
                ["WARN: MEDIUM band with no card (not gated in v1; HIGH/CRITICAL still fail)"],
            )
        return GateResult(
            False,
            score,
            band,
            ["MEDIUM band requires a card annotating each finding as accepted with a note"],
        )

    index = _card_findings_index(card)
    reasons: list[str] = []
    for finding in findings:
        rid = _rule_id(finding)
        entry = index.get(rid)
        if entry is None:
            reasons.append(f"finding {rid or '?'} is not recorded on the card")
        elif entry.get("status") != "accepted":
            reasons.append(f"finding {rid} is not status: accepted on the card")
        elif not str(entry.get("note") or "").strip():
            reasons.append(f"finding {rid} is accepted but has no note on the card")

    if reasons:
        return GateResult(False, score, band, reasons)
    return GateResult(True, score, band, ["MEDIUM band: every finding accepted and noted"])


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_card(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    if path.endswith(".json"):
        return _load_json(path)
    # Lazy import so the gate has no hard dependency on PyYAML unless a
    # skill-card.md is passed as the card.
    from skillcard.cli import load_card_md  # noqa: PLC0415

    return load_card_md(path)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="skillcard-gate",
        description="Apply the Califa Cards security gate to a SkillSpector JSON report.",
    )
    parser.add_argument("report", help="path to a SkillSpector --format json report")
    parser.add_argument(
        "--card",
        default=None,
        help="optional skill-card (card.json or skill-card.md) supplying finding notes",
    )
    parser.add_argument(
        "--warn-medium-without-card",
        action="store_true",
        help="treat a MEDIUM band with no card as a warning (exit 0), not a failure",
    )
    args = parser.parse_args(argv)

    report = _load_json(args.report)
    card = _load_card(args.card)
    result = evaluate(report, card, warn_medium_without_card=args.warn_medium_without_card)
    print(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
