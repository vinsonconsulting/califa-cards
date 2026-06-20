# Skill card review — textual

Each HUMAN field below needs sign-off: put an x in its checkbox once you
have verified it. `skillcard review` / `make check` blocks until every box
is checked. Regenerating the card with changed content resets this checklist.

fingerprint: sha256:aa88695f624cb108118069cd9456aecf2df2f2489db6bf6a93032c720f7576af

- [x] `summary` — Build and debug Python TUIs with Textual, covering widgets, reactive attributes, TCSS layout, screens, and the test harness.
- [x] `triggers` — 6 positive / 3 negative
- [x] `output` — {'type': 'Code', 'format': 'Markdown with Python + TCSS code blocks'}
- [x] `dependencies` — ['textual>=0.80,<1.0', 'python>=3.9']
- [x] `external_endpoints` — none
- [x] `permissions` — network=false shell=true file=true env=false mcp=false
- [x] `status` — stable
- [x] `scan.findings[AST4]` — accepted: "subprocess invokes textual run and pytest; scoped to the workspace and documented in SKILL.md"
