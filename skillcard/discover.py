"""discover.py -- walk a skill directory into a card context (SPEC.md section C).

The first stage of the generator chain: a *pure read* of a skill bundle into the
card dict that :mod:`skillcard.build_card` validates and writes. Sources:

* ``SKILL.md`` frontmatter -- ``name``/``version``/``description`` plus an
  authored ``card:`` block (the fields a generator cannot infer: summary,
  triggers, output, dependencies, permissions, status, finding decisions).
* ``.skillcard.toml`` (nearest, walking up) -- repo config shared across a
  cabinet: owner, repo tier/url, license, homepage, the scanner pin.
* the SkillSpector JSON report (``report.json`` or committed ``scan.json``) --
  score, severity band, date, findings.
* ``evals/evals.json`` -- a ``results`` block becomes the metrics scorecard;
  its absence is the beta path (no metrics).
* git + :mod:`skillcard.hashing` -- provenance (``source_commit``, ``updated``,
  ``content_hash``), unless the ``card:`` block pins commit/date for a fixture.

discover leaves genuinely missing required fields *absent* rather than guessing,
so build_card's schema validation is the single, clear refusal point.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillcard import gate
from skillcard.cli import parse_frontmatter
from skillcard.hashing import _source_files, content_hash

# Fields the author owns and a human must sign off on (drives review.py).
HUMAN_FIELDS = frozenset(
    {
        "summary",
        "triggers",
        "inputs",
        "output",
        "dependencies",
        "external_endpoints",
        "permissions",
        "status",
    }
)


@dataclass
class DiscoverResult:
    skill_dir: Path
    card: dict[str, Any]
    provenance: dict[str, str]  # top-level field -> "inferred" | "human"


# --- individual sources ---------------------------------------------------------


def _read_skill_md(skill_dir: Path) -> dict[str, Any]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"{skill_dir}: no SKILL.md to discover")
    return parse_frontmatter(skill_md.read_text(encoding="utf-8"))


def _read_repo_config(skill_dir: Path) -> dict[str, Any]:
    """Nearest ``.skillcard.toml`` walking up from the skill dir; {} if none."""
    for parent in [skill_dir, *skill_dir.parents]:
        cfg = parent / ".skillcard.toml"
        if cfg.exists():
            return tomllib.loads(cfg.read_text(encoding="utf-8"))
    return {}


def _find_report(skill_dir: Path, report_path: str | Path | None) -> dict[str, Any]:
    if report_path is not None:
        return json.loads(Path(report_path).read_text(encoding="utf-8"))
    # report.json is the transient name `make scan` writes; scan.json is the
    # committable fixture name (both are excluded from content_hash).
    for name in ("report.json", "scan.json"):
        candidate = skill_dir / name
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"{skill_dir}: no scan report (looked for report.json, scan.json, or --report)"
    )


def _tag(tags: list[str], *prefixes: str) -> str | None:
    for t in tags or []:
        if any(str(t).startswith(p) for p in prefixes):
            return str(t)
    return None


def _scan(skill_dir: Path, report: dict[str, Any], cfg: dict[str, Any],
          decisions: dict[str, Any]) -> dict[str, Any]:
    score = gate.extract_score(report)
    tool = cfg.get("scan_tool")
    if not tool:
        version = (report.get("metadata") or {}).get("skillspector_version", "unknown")
        tool = f"skillspector@{version}"
    scanned_at = (report.get("skill") or {}).get("scanned_at", "")
    scan_date = scanned_at[:10] if scanned_at else None

    findings = []
    for issue in gate.extract_findings(report):
        rid = gate._rule_id(issue)
        decision = decisions.get(rid, {})
        findings.append(
            {
                "rule_id": rid,
                "severity": str(issue.get("severity", "LOW")).upper(),
                "status": decision.get("status", "resolved"),
                "owasp": _tag(issue.get("tags", []), "ASI"),
                "atlas": _tag(issue.get("tags", []), "AML."),
                "note": decision.get("note"),
            }
        )
    return {
        "tool": tool,
        "score": score,
        "severity": gate.severity_band(score),
        "date": scan_date,
        "findings": findings,
        "sarif": "./report.sarif",
    }


def _metrics(skill_dir: Path, card_block: dict[str, Any]) -> dict[str, Any] | None:
    evals_path = skill_dir / "evals" / "evals.json"
    if not evals_path.exists():
        return None
    results = json.loads(evals_path.read_text(encoding="utf-8")).get("results")
    if not results:
        return None  # the beta path: an evals file with no aggregate results yet
    trig = results.get("triggering", {})
    func = results.get("functional", {})
    harness = results.get("harness") or trig.get("harness", "")
    notes = card_block.get("metrics_notes") or trig.get("note") or func.get("note")
    metrics = {
        "trigger_precision": trig.get("precision"),
        "trigger_recall": trig.get("recall"),
        "near_miss_precision": trig.get("near_miss_precision"),
        "task_completion_rate": func.get("task_completion_rate"),
        "tool_call_delta": func.get("tool_call_delta"),
        "token_efficiency": func.get("token_efficiency"),
        "eval_pass_rate": func.get("eval_pass_rate"),
        "harness": harness,
        "notes": notes,
    }
    return metrics


def _git_facts(skill_dir: Path) -> tuple[str | None, str | None]:
    """Last commit (SHA, YYYY-MM-DD) touching the skill's *source* files.

    Scoped to source files -- not the whole dir -- so committing the generated
    card.json/skill-card.md never advances source_commit (keeps build idempotent).
    """
    sources = [p.relative_to(skill_dir).as_posix() for p in _source_files(skill_dir)]
    if not sources:
        return None, None
    try:
        out = subprocess.run(
            ["git", "-C", str(skill_dir), "log", "-1", "--format=%H%n%cs", "--", *sources],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\n")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None
    if len(out) >= 2 and out[0]:
        return out[0], out[1]
    return None, None


# --- assembly -------------------------------------------------------------------


def discover(skill_dir: str | Path, report_path: str | Path | None = None) -> DiscoverResult:
    skill_dir = Path(skill_dir)
    skill_md = _read_skill_md(skill_dir)
    card_block: dict[str, Any] = skill_md.get("card") or {}
    cfg = _read_repo_config(skill_dir)
    decisions = card_block.get("findings") or {}

    pinned_commit = card_block.get("source_commit")
    pinned_updated = card_block.get("updated")
    git_commit, git_date = _git_facts(skill_dir)
    source_commit = pinned_commit or git_commit
    updated = pinned_updated or git_date

    card: dict[str, Any] = {
        # identity and provenance
        "name": skill_md.get("name"),
        "version": _as_str(skill_md.get("version")),
        "summary": card_block.get("summary"),
        "owner": cfg.get("owner"),
        "repo": {"tier": cfg.get("tier"), "url": cfg.get("url")},
        "license": cfg.get("license"),
        "homepage": cfg.get("homepage"),
        "source_commit": source_commit,
        "content_hash": content_hash(skill_dir),
        # capability and behavior
        "description": _scalar(skill_md.get("description")),
        "triggers": card_block.get("triggers"),
        "inputs": card_block.get("inputs"),
        "output": card_block.get("output"),
        "dependencies": card_block.get("dependencies"),
        "external_endpoints": card_block.get("external_endpoints"),
        "permissions": card_block.get("permissions"),
        # quality scorecard
        "metrics": _metrics(skill_dir, card_block),
        # security
        "scan": _scan(skill_dir, _find_report(skill_dir, report_path), cfg, decisions),
        # lifecycle
        "status": card_block.get("status"),
        "card_version": _as_str(card_block.get("card_version", "1.0")),
        "updated": updated,
    }

    provenance = {key: ("human" if key in HUMAN_FIELDS else "inferred") for key in card}
    return DiscoverResult(skill_dir=skill_dir, card=card, provenance=provenance)


def _scalar(value: Any) -> Any:
    """Collapse a YAML folded/multi-line string to a single trimmed line."""
    if isinstance(value, str):
        return " ".join(value.split())
    return value


def _as_str(value: Any) -> Any:
    """Versions like 1.0 can parse as floats in YAML; the schema wants strings."""
    if isinstance(value, (int, float)):
        return str(value)
    return value
