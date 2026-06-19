"""Califa Cards skill-card schema (SPEC.md section A).

This pydantic v2 model is the single source of truth for the skill-card
standard. The cabinets' ``make check`` and the discover Worker's ingest
validator both import :class:`SkillCard` from here, so a field change here is
a change to the standard everywhere it is consumed.

Canonical form is YAML frontmatter in ``skill-card.md`` (the human view),
derived 1:1 to ``card.json`` (the machine view and Worker index payload).

Required [R] fields are plain (no default); optional [O] fields default to
``None``. ``extra="forbid"`` rejects unknown keys at every level, so a typo'd
field is a hard error rather than a silently dropped value.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# A slug is kebab-case: lowercase alphanumerics joined by single hyphens.
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
# Semver, with an optional patch so card_version "1.0" is accepted alongside
# a full "1.2.0". Pre-release and build metadata suffixes are permitted.
SEMVER_PATTERN = r"^\d+\.\d+(\.\d+)?(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class _Base(BaseModel):
    """Common config: reject unknown keys everywhere."""

    model_config = ConfigDict(extra="forbid")


# --- A.1 Identity and provenance ------------------------------------------------


class Repo(_Base):
    tier: Literal["public", "private"]
    url: str


class Signature(_Base):
    """Optional, v3+. Path to the OMS signature plus an optional cert reference."""

    path: str
    cert: str | None = None


# --- A.2 Capability and behavior ------------------------------------------------


class NegativeTrigger(_Base):
    """A near-miss prompt and the sibling skill that should handle it instead."""

    prompt: str
    use_instead: str


class Triggers(_Base):
    positive: list[str] = Field(min_length=1)
    negative: list[NegativeTrigger] = Field(min_length=1)


class Output(_Base):
    type: str
    format: str


class Permissions(_Base):
    network: bool
    shell: bool
    file: bool
    env: bool
    mcp: bool


# --- A.3 Quality scorecard ------------------------------------------------------


class Metrics(_Base):
    trigger_precision: float = Field(ge=0.0, le=1.0)
    trigger_recall: float = Field(ge=0.0, le=1.0)
    near_miss_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    task_completion_rate: float = Field(ge=0.0, le=1.0)
    tool_call_delta: float | None = None
    token_efficiency: float | None = None
    eval_pass_rate: float = Field(ge=0.0, le=1.0)
    harness: str


# --- A.4 Security ---------------------------------------------------------------


class Finding(_Base):
    """One SkillSpector finding as recorded on the card.

    ``rule_id`` carries the SkillSpector rule (which may be a behavioral-AST
    code such as ``AST4``). ``owasp`` carries the OWASP Agent Security
    Initiative code (for example ``ASI02``) and is ``None`` for AST-only
    findings that have no ASI mapping. ``atlas`` carries the MITRE ATLAS id
    (for example ``AML.T0050``).
    """

    rule_id: str
    severity: Severity
    status: Literal["resolved", "accepted"]
    owasp: str | None = None
    atlas: str | None = None
    note: str | None = None


class Scan(_Base):
    tool: str
    score: int = Field(ge=0, le=100)
    severity: Severity
    date: date
    findings: list[Finding]
    sarif: str


# --- Top-level card (A.5 lifecycle folded in) -----------------------------------


class SkillCard(_Base):
    # A.1 identity and provenance
    name: str = Field(pattern=SLUG_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    summary: str
    owner: str
    repo: Repo
    license: str
    homepage: str | None = None
    source_commit: str
    content_hash: str
    signature: Signature | None = None
    # A.2 capability and behavior
    description: str
    triggers: Triggers
    inputs: list[str] | None = None
    output: Output
    dependencies: list[str]
    external_endpoints: Literal["none"] | list[str]
    permissions: Permissions
    # A.3 quality scorecard. Required only for status: stable (see the validator
    # below); draft/beta/deprecated cards may omit metrics, since the eval
    # harness that produces them is a v2 deliverable.
    metrics: Metrics | None = None
    # A.4 security
    scan: Scan
    # A.5 lifecycle
    status: Literal["draft", "beta", "stable", "deprecated"]
    card_version: str = Field(pattern=SEMVER_PATTERN)
    updated: date

    @model_validator(mode="after")
    def _metrics_required_for_stable(self) -> SkillCard:
        """A ``stable`` card must carry a quality scorecard.

        Lifecycle refinement (2026-06-19): metrics are the v2 eval-harness
        output, so draft/beta/deprecated cards may ship without them, but a
        skill promoted to ``stable`` must publish its measured quality.
        """
        if self.status == "stable" and self.metrics is None:
            raise ValueError("metrics are required when status is 'stable'")
        return self
