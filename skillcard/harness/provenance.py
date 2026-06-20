"""Harness provenance string for ``metrics.harness`` (SPEC.md section A.3 / D).

The format mirrors SPEC A.3 (``<harness>@<sha> / <model-id> / <date>``). This
wrapper ports the namespace-isolated fork, so it attributes to that fork rather
than to raw skill-creator (whose parallel path produced the 0.139 artifact).
"""

from __future__ import annotations

from skillcard.harness.trigger import FORK_SHA


def harness_provenance(model: str, date: str, sha: str | None = None) -> str:
    """Return ``skill-eval-fork@<sha> / <model> / <date>``."""
    return f"skill-eval-fork@{sha or FORK_SHA} / {model} / {date}"
