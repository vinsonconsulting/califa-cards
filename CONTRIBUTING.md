# Contributing to Califa Cards

Thanks for helping shape the skill-card standard. This repo is small and
opinionated; the rules below keep it that way.

## Ground rules

- The schema in `schema/schema.py` is the single source of truth. If you change
  a field, update SPEC.md section A and the worked example in the same change,
  and add or adjust a test.
- The standard is consumed by two cabinets and (in v2) by the discover Worker's
  ingest validator. A schema change is a breaking change to all of them; bump
  `card_version` semantics accordingly and call it out in the PR.
- No em-dashes in the docs.

## Workflow

1. Branch from `main`. The initial scaffold was committed straight to `main`;
   everything after that goes through a feature branch and a PR.
2. `make dev` once to set up `.venv` with the dev and scan extras.
3. Make your change. Write or update tests under `tests/`.
4. `make check` must pass: ruff lint, pytest, and a clean self-scan (LOW band).
5. Open a PR. Keep `main` at +0/-0 between merges.

## What `make check` enforces

- **Lint:** `ruff check .`
- **Tests:** the schema validates the worked example and rejects malformed
  cards; the gate honors every score band and the CRITICAL-severity override.
- **Self-scan:** `skillspector scan` of this repo's shipping packages
  (`skillcard`, `schema`), gated by `skillcard/gate.py`, must land in the LOW
  band. It scans the packages rather than the whole tree because SkillSpector
  is a skill scanner; see SPEC.md section E.

## Security findings

The gate does not reject a finding for existing. It rejects a finding for being
un-accepted or un-noted. If your change introduces a legitimate `subprocess` or
`shell` use, expect it to surface as a finding, and record it on the relevant
card with `status: accepted` and a note that justifies it. See SPEC.md section
E.

## SkillSpector

SkillSpector is a git-only install:
`pip install git+https://github.com/NVIDIA/SkillSpector`. `make dev` pulls it in
through the `scan` extra. It needs Python 3.12 to 3.14.
