# Califa Cards: A Portable, Versioned Format for Documenting/Scoring Claude Skills

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![build](https://img.shields.io/badge/build-make%20check-brightgreen.svg)](Makefile)
[![python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![status](https://img.shields.io/badge/status-pre--1.0-yellow.svg)](SPEC.md)

A specification and toolkit for **Skill Cards**: a portable, versioned format for
documenting and scoring Claude Skills, plus the tooling that produces and enforces it.

Think of a Skill Card as the nutrition label for an agent skill. It records who made the
skill, what it triggers on, how it scores on a set of evaluation metrics, what it
is allowed to touch, and whether a security scanner cleared it. Califa Cards
defines that label and ships the tooling that generates and validates it.

## Why a Card Format?

A skill is easy to write and hard to compare. Two skills that claim the same job
can differ in what fires them, in what they are permitted to do, and in how often
they actually finish the task. A Skill Card attempts to pin that down in one structured file.
Because the card is versioned and machine-readable, a skill's triggering behavior,
its security posture, and its task-completion record can be tracked over time and
compared across a whole library.

The card is the artifact. Deciding what to measure, how to record it, and how to
enforce it is the work this repo represents.

## What's in the repo

- **The spec.** [`SPEC.md`](SPEC.md) is the normative standard, in sections A
  through H: the schema (A), a worked example (B), the generator (C), the metrics
  (D), the scan gate (E), badges (F), the discover Worker (G), and the roadmap (H).
  The pydantic model in [`schema/schema.py`](schema/schema.py) is the single source
  of truth where prose and code might disagree.
- **The schema.** A card carries identity and provenance (name, version, owner,
  repo, license, source commit, and a content hash over the skill's source);
  capability and behavior (the triggering description, positive and negative trigger
  cases, declared inputs and output, dependencies, and a permissions block for
  network, shell, file, env, and mcp access); a quality scorecard (trigger precision
  and recall, task-completion and eval pass rates, with the harness that produced
  them); and a security block (the scanner, score, severity, and findings). Section
  A has the full field list.
- **The tooling.** [`skillcard`](skillcard/cli.py) is a Python CLI (3.12+). Its
  subcommands: `validate` (check a card against the schema and its content hash),
  `build` (generate a card from a skill directory), `gate` (apply the
  security-score policy), `hash` (compute the content hash), `review` (block until
  human-authored fields are signed off), `eval` (run the triggering and functional
  metrics harness), `optimize` (tune a skill's description against its trigger set),
  and `badges` (emit shields.io endpoint JSON per metric).
- **A worked example.** [`examples/textual/`](examples/textual/) cards a real skill
  end to end: the authored `SKILL.md` and `card.authored.yaml` inputs, and the
  generated `card.json` and `skill-card.md`. A regression test regenerates it byte
  for byte, so the example stays honest.

## How it fits

[**claude-skill-foundry**](https://github.com/vinsonconsulting/claude-skill-foundry)
is the public corpus carded with this spec. It vendors the `skillcard` tooling and
produces a `card.json` plus a rendered `skill-card.md` for every skill it holds, so
you can read cards in the wild rather than only the format on paper. A private
skills repository is the second consumer.

A card's `scan` block carries the result of
[**NVIDIA SkillSpector**](https://github.com/NVIDIA/SkillSpector), a static risk
scanner for agent skills. Califa Cards defines the card; SkillSpector is a separate
tool whose output the card records. The scanner reports a 0 to 100 risk score where
a lower number is better, so 0 to 20 is the LOW band. The gate in
[`skillcard/gate.py`](skillcard/gate.py) requires either a LOW result or every
higher finding explicitly accepted with a note. There is no Anthropic involvement
in any of this.

## Carding a skill

A repository that holds skills installs Califa Cards as a dev dependency and
validates each card against the standard.

```bash
# Install the spec, schema, and CLI (with the scan extra).
pip install "califa-cards[scan] @ git+https://github.com/vinsonconsulting/califa-cards"

# Generate a card from a skill directory.
skillcard build path/to/skill

# Validate the card against the schema and its content hash.
skillcard validate path/to/skill/card.json

# Scan the skill, then gate the result. The gate reads the JSON report.
skillspector scan path/to/skill --no-llm --format json --output report.json
skillcard gate report.json --card path/to/skill/card.json
```

For CI, copy [`ci/skill-card-scan.yml`](ci/skill-card-scan.yml) into a repo's
workflows. It runs the SkillSpector static pass, uploads SARIF to the GitHub
Security tab, and runs the gate.

The metrics harness (`skillcard eval` and `skillcard optimize`) makes live `claude`
calls and spends tokens, so both stay out of the standard `make check` gate and
require an explicit `--i-understand-this-spends-tokens` flag.

## Maturity (v0.8.0, pre-1.0)

| Piece | State |
| --- | --- |
| Schema and validator | Built |
| `skillcard` CLI (validate / build / gate / hash / review / eval / optimize / badges) | Built |
| Security-score gate | Built |
| Metrics harness (triggering + functional) | Built; spends tokens, runs outside `make check` |
| Badges (shields.io endpoints) | Built |
| Discover Worker (sections G, H) | Specified; design stub, not yet implemented |

`make check` is the gate for every change: ruff lint, the pytest suite (schema,
gate, generator, and harness), and a SkillSpector self-scan of this repo's own
tooling that has to land in the LOW band.

## Develop on Califa itself

```bash
make dev      # create .venv and install with the dev and scan extras
make check    # ruff lint + pytest + a clean SkillSpector self-scan
```

## License

Apache-2.0. See [LICENSE](LICENSE).
