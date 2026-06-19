---
name: "textual"
version: "1.2.0"
summary: "Build and debug Python TUIs with Textual, covering widgets, reactive attributes, TCSS layout, screens, and the test harness."
owner: "@vinsonconsulting"
repo: { tier: "public", url: "https://github.com/vinsonconsulting/jims-filing-cabinet-of-claude-skills" }
license: "MIT"
source_commit: "9f3a1c2"
content_hash: "sha256:115aa2d36568604e00dac60c2b13666db39d975b77b28a5312a3bba8a1ae2e0e"
description: "Build, style, and debug terminal user interfaces in Python with Textual. Use when the user mentions Textual, a TUI, App/Widget/Screen subclasses, reactive attributes, TCSS or Textual CSS, `textual run`, `textual console`, or compose(). Do NOT use for plain CLI argument parsing (use click-cli), Rich-only static output (use rich-render), or curses (use curses)."
triggers:
  positive:
    - "build a Textual app with a data table and a footer"
    - "my reactive attribute isn't updating the widget"
    - "lay out two panels side by side with TCSS"
    - "push a modal screen and return a value when it dismisses"
    - "why does textual run show a blank screen"
    - "write a pytest harness that pilots my Textual app"
  negative:
    - { prompt: "parse these command-line flags", use_instead: "click-cli" }
    - { prompt: "print a colored table to stdout", use_instead: "rich-render" }
    - { prompt: "draw directly with curses windows", use_instead: "curses" }
output: { type: "Code", format: "Markdown with Python + TCSS code blocks" }
dependencies: ["textual>=0.80,<1.0", "python>=3.9"]
external_endpoints: "none"
permissions: { network: false, shell: true, file: true, env: false, mcp: false }
metrics:
  trigger_precision: 0.95
  trigger_recall: 0.88
  near_miss_precision: 1.0
  task_completion_rate: 0.83
  eval_pass_rate: 0.86
  harness: "skill-creator@b0cbd3d / claude-opus-4-8 / 2026-06-17"
scan:
  tool: "skillspector@a5092dd"
  score: 12
  severity: "LOW"
  date: "2026-06-17"
  sarif: "./report.sarif"
  findings:
    - { rule_id: "AST4", severity: "MEDIUM", status: "accepted", owasp: null, atlas: "AML.T0050", note: "subprocess invokes textual run and pytest; scoped to the workspace and documented in SKILL.md" }
status: "stable"
card_version: "1.0"
updated: "2026-06-18"
---

# textual <small>v1.2.0</small>

Build and debug Python TUIs with Textual, covering widgets, reactive attributes, TCSS layout, screens, and the test harness.

**Status:** stable | **License:** MIT | **Scan:** LOW (12/100)

## When to use it

Build, style, and debug terminal user interfaces in Python with Textual. Use when the user mentions Textual, a TUI, App/Widget/Screen subclasses, reactive attributes, TCSS or Textual CSS, `textual run`, `textual console`, or compose(). Do NOT use for plain CLI argument parsing (use click-cli), Rich-only static output (use rich-render), or curses (use curses).

## Quality scorecard

| Metric | Value |
| --- | --- |
| Trigger precision | 0.95 |
| Trigger recall | 0.88 |
| Near-miss precision | 1.0 |
| Task completion | 0.83 |
| Eval pass rate | 0.86 |

Harness: `skill-creator@b0cbd3d / claude-opus-4-8 / 2026-06-17`

## Security

SkillSpector scan `skillspector@a5092dd` scored 12/100 (LOW band).

Findings:

- `AST4` (MEDIUM, accepted) — subprocess invokes textual run and pytest; scoped to the workspace and documented in SKILL.md

The SARIF report lives at `./report.sarif`.
