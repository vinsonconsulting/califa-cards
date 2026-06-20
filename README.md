# Califa Cards

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![build](https://img.shields.io/badge/build-make%20check-brightgreen.svg)](Makefile)
[![python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![status](https://img.shields.io/badge/status-WIP-yellow.svg)](SPEC.md)

**A Comprehensive Skill Card Standard and Testing Framework.**

A skill card is the nutrition label for an agent skill: who made it, what it
triggers on, how well it scores, what it is allowed to touch, and whether a
security scanner cleared it. Califa Cards is the standard for that label plus
the tooling that produces and enforces it.

## ⚓ The Califa lineage

California is named for Queen Califa, the warrior ruler of a mythical island
from a 1510 Spanish romance. The three points of this project sit on her coast:
Anthropic in San Francisco, NVIDIA in Santa Clara, and this repo's author in
Livermore. Claude writes and validates the cards, NVIDIA's SkillSpector scans
them, and Califa is the standard that ties the two together. The name is a small
monument to the geography of the supply chain.

## 🧭 Framework versus cards

There are two kinds of thing in this world, and Califa is the first kind.

- **The framework (this repo).** The normative spec, the pydantic schema, the
  security gate, the generator tooling, the discover Worker design, and the CI
  templates. This is the standard and the machinery.
- **The cards (the cabinets).** Each skill in a cabinet carries a canonical
  `card.json` (machine view) plus its rendered `skill-card.md` (human view),
  generated from the `SKILL.md` identity frontmatter and a `card.authored.yaml`
  governance sidecar. The cabinets consume Califa as a development dependency;
  they do not vendor a copy of the rules.

`jims-filing-cabinet-of-claude-skills` (public) and
`jims-secret-cabinet-of-mysteries` (private) are the first two consumers.

## What is functional in v0

| Piece | State |
| --- | --- |
| `schema/schema.py` | Functional. The pydantic v2 model of the standard (spec section A) and the single source of truth. |
| `skillcard/gate.py` | Functional. The SkillSpector score gate (spec section E). |
| `skillcard/cli.py` | `validate`, `gate`, `hash`, `build`, and `review` are functional; `badges` is a v2 stub. |
| `examples/textual/` | The reference card: authored `SKILL.md` + `card.authored.yaml` inputs, and the generated `card.json` / `skill-card.md`. |
| Generator modules, discover Worker | Documented stubs for v2 (spec sections C, G, H). |

## 🗝️ Quickstart: how a cabinet consumes Califa

A cabinet validates its cards against Califa's schema and gates them with
Califa's scanner policy.

```bash
# In the cabinet, install Califa (and its scan extra) as a dev dependency.
pip install "califa-cards[scan] @ git+https://github.com/vinsonconsulting/califa-cards"

# Validate a card against the standard.
skillcard validate skills/tui/textual/card.json

# Scan a skill and gate the result. The gate reads the JSON report.
skillspector scan skills/tui/textual --no-llm --format json --output report.json
skillcard gate report.json --card skills/tui/textual/card.json
```

For CI, copy [`ci/skill-card-scan.yml`](ci/skill-card-scan.yml) into the
cabinet's `.github/workflows/`. It runs the SkillSpector static pass, uploads
SARIF to the GitHub Security tab, and runs the gate.

## Develop on Califa itself

```bash
cd /path/to/califa-cards
make dev      # create .venv and install with the dev and scan extras
make check    # ruff lint + pytest + a clean SkillSpector self-scan
```

`make check` is the gate for every change. It lints, runs the schema and gate
tests, and scans this repo's own tooling, requiring it to land in the LOW band.

## Two things this build resolved

- **The score is not in SARIF.** SkillSpector writes the 0 to 100 risk score
  and exact severities to its JSON report, not its SARIF. SARIF collapses
  CRITICAL and HIGH into one level and carries no score. So the gate reads JSON;
  SARIF is kept for the GitHub Security tab. See SPEC.md section E.
- **`owasp` carries ASI codes.** Findings map to OWASP Agent Security Initiative
  codes (for example `ASI02`) in their tags, with MITRE ATLAS ids alongside. The
  `AST1` to `AST8` codes are SkillSpector's own rule ids, not an OWASP taxonomy.
  See SPEC.md, resolved items.

## Read the standard

[**SPEC.md**](SPEC.md) is the normative standard: schema (A), worked example
(B), generator (C), metrics (D), scan gate (E), badges (F), discover Worker (G),
and the phased roadmap (H).

## License

Apache-2.0. See [LICENSE](LICENSE).
