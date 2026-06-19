---
name: textual
version: "1.2.0"
description: >-
  Build, style, and debug terminal user interfaces in Python with Textual. Use
  when the user mentions Textual, a TUI, App/Widget/Screen subclasses, reactive
  attributes, TCSS or Textual CSS, `textual run`, `textual console`, or
  compose(). Do NOT use for plain CLI argument parsing (use click-cli),
  Rich-only static output (use rich-render), or curses (use curses).
card:
  summary: Build and debug Python TUIs with Textual, covering widgets, reactive attributes, TCSS layout, screens, and the test harness.
  status: stable
  card_version: "1.0"
  source_commit: "9f3a1c2"
  updated: "2026-06-18"
  output: { type: Code, format: "Markdown with Python + TCSS code blocks" }
  dependencies: ["textual>=0.80,<1.0", "python>=3.9"]
  external_endpoints: none
  permissions: { network: false, shell: true, file: true, env: false, mcp: false }
  triggers:
    positive:
      - "build a Textual app with a data table and a footer"
      - "my reactive attribute isn't updating the widget"
      - "lay out two panels side by side with TCSS"
      - "push a modal screen and return a value when it dismisses"
      - "why does textual run show a blank screen"
      - "write a pytest harness that pilots my Textual app"
    negative:
      - { prompt: "parse these command-line flags", use_instead: click-cli }
      - { prompt: "print a colored table to stdout", use_instead: rich-render }
      - { prompt: "draw directly with curses windows", use_instead: curses }
  findings:
    AST4:
      status: accepted
      note: "subprocess invokes textual run and pytest; scoped to the workspace and documented in SKILL.md"
---

# textual

Reference skill bundle used as the Califa Cards generator fixture. The
`skillcard build examples/textual/` regression test regenerates `card.json` and
`skill-card.md` from this `SKILL.md`, the repo config, the committed scan
report, and the evals results — and must reproduce the committed pair byte for
byte (the deterministic acceptance proof in SPEC.md section C).

Everything the generator needs lives in this directory:

- `SKILL.md` — name, version, description, and the authored `card:` block.
- `.skillcard.toml` — repo config (owner, repo tier/url, license, scanner pin).
- `scan.json` — the SkillSpector `--format json` report.
- `evals/evals.json` — eval definitions plus the aggregate `results` block.
