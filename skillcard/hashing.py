"""Content hashing for skill cards (SPEC.md section A.1).

``content_hash`` is a deterministic SHA256 over the skill's *source* files, so a
card can declare exactly which bytes it describes. It deliberately excludes the
generated card and scan artifacts (``skill-card.md``, ``card.json``,
``scan.json``, ``report.json``, ``report.sarif``) so the hash never depends on
itself, plus the authored governance sidecar (``card.authored.yaml``) so editing
status or a finding decision never moves the *code*-identity hash, plus the eval
harness output (``evals/evals.json``) so running ``skillcard eval`` -- which
rewrites it with a fresh date -- never moves the hash either (the authored eval
*set* it grades against stays hashed as the test contract), plus the usual
editor/VCS noise (``.DS_Store``, ``__pycache__``, ``.git``).

Algorithm (normative):

1. Walk ``skill_dir`` recursively for regular files, dropping the exclusions.
2. For each file, build the line ``"<sha256-hex>  <posix-relpath>"`` where the
   path is relative to ``skill_dir`` with ``/`` separators.
3. Sort the lines by relative path, join with ``"\\n"`` (no trailing newline).
4. The result is ``"sha256:" + sha256(manifest-utf8)``.

The two-space separator mirrors the ``sha256sum`` manifest convention, so the
intermediate manifest is human-auditable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Generated artifacts (would make the hash self-referential) and editor/VCS noise.
# ``report.json`` and ``scan.json`` are both names the SkillSpector JSON pass may
# write into a skill dir; ``card-review.md`` is the generator's sign-off
# checklist; ``card.authored.yaml`` is the authored governance overlay (status,
# accepted-finding notes, provenance pins); ``evals/evals.json`` is the metrics
# harness output (run provenance + the results block, rewritten with a fresh date
# every run). None is source, so none enters the hash -- and because this set also
# drives ``_source_files`` (and thus the git-scoped ``source_commit``), neither the
# sidecar nor the eval output advances provenance either. The authored eval *set*
# (``triggering.jsonl``, ``functional/{tasks.json,run_grader.py,graders.py}``,
# ``fixtures/``) is NOT excluded: it is the test contract and stays hashed.
EXCLUDE_NAMES = frozenset(
    {
        "skill-card.md",
        "card.json",
        "card-review.md",
        "card.authored.yaml",
        "scan.json",
        "report.json",
        "report.sarif",
        "evals.json",
        ".DS_Store",
    }
)
EXCLUDE_DIR_PARTS = frozenset({"__pycache__", ".git"})


def _source_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(skill_dir).parts
        if path.name in EXCLUDE_NAMES:
            continue
        if any(part in EXCLUDE_DIR_PARTS for part in rel_parts):
            continue
        files.append(path)
    return files


def build_manifest(skill_dir: Path) -> str:
    """Return the sorted ``<sha256>  <relpath>`` manifest for the skill dir."""
    skill_dir = Path(skill_dir)
    lines: list[str] = []
    for path in _source_files(skill_dir):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rel = path.relative_to(skill_dir).as_posix()
        lines.append(f"{digest}  {rel}")
    lines.sort(key=lambda line: line.split("  ", 1)[1])
    return "\n".join(lines)


def content_hash(skill_dir: Path) -> str:
    """Return ``"sha256:<hex>"`` over the skill's sorted source manifest."""
    manifest = build_manifest(Path(skill_dir))
    return "sha256:" + hashlib.sha256(manifest.encode("utf-8")).hexdigest()
