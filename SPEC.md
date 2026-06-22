# Califa Cards: Unified Skill Card and Scorecard Standard

Status: decisions locked 2026-06-18. This document is the normative standard.
The pydantic model in `schema/schema.py` is the machine-enforceable form of
section A and is the single source of truth where the prose and the code could
ever disagree.

## Responsibility split

Califa Cards (this repo) owns the normative spec, the pydantic schema, the
generator tooling, the security gate, the discover Worker, the CI templates,
and the badge tooling. The two cabinets keep a per-skill `card.json` plus its
rendered `skill-card.md` view next to each `SKILL.md`, and they consume Califa as
a development dependency.

Canonical format (refined 2026-06-19): authored inputs — `SKILL.md` frontmatter
for *identity* and a `card.authored.yaml` sidecar for *governance* — generate
`card.json`, the canonical machine payload the Worker indexes, which renders
one-way to `skill-card.md`, the human view. The pipeline is one-directional:
inputs → `card.json` → `skill-card.md`. The view is never parsed back, so it
optimizes for readability rather than round-trip fidelity.

---

## A. Merged field schema

Notation: `[R]` required, `[O]` optional. Slugs are kebab-case and match the
regex `^[a-z0-9]+(-[a-z0-9]+)*$`. Versions are semver (an absent patch is
allowed so `card_version: 1.0` is valid).

### A.1 Identity and provenance

| Field | Req | Type | Notes |
| --- | --- | --- | --- |
| `name` | R | slug | Equals the SKILL.md name and the directory name. |
| `version` | R | semver | Mirrors the SKILL.md version. |
| `summary` | R | string | One sentence, distinct from the triggering `description`. |
| `owner` | R | string | Handle or username. |
| `repo` | R | object | `{tier: public \| private, url}`. |
| `license` | R | SPDX string | For example MIT, Apache-2.0. |
| `homepage` | O | URL | Optional link. |
| `source_commit` | R | git SHA | The commit the card describes; from git (source-scoped) or a `card.authored.yaml` pin. |
| `content_hash` | R | string | SHA256 over the sorted file manifest (algorithm below). |
| `signature` | O | object | Path to `skill.oms.sig` plus a cert reference (v3+). |

The `content_hash` is computed by `skillcard hash <skill-dir>` and re-verified by
`skillcard validate <skill-dir>`. Algorithm (normative):

1. Walk the skill directory recursively for regular files, **excluding** the
   generated artifacts `skill-card.md`, `card.json`, `card-review.md`,
   `scan.json`, `report.json`, `report.sarif` (so the hash never references
   itself), the authored governance sidecar `card.authored.yaml` (governance is
   overlay, not the code the hash describes), the metrics harness output
   `evals/evals.json` (run provenance + the results block, rewritten with a fresh
   date every run — so populating or re-running metrics never moves the
   code-identity hash; the authored eval *set* it grades against stays hashed),
   and the noise paths `.DS_Store`, `__pycache__/`, `.git/`.
2. For each remaining file, form the line `<sha256-hex>␠␠<posix-relpath>` (two
   spaces, `sha256sum` style), where the path is relative to the skill dir.
3. Sort the lines by relative path and join them with `\n` (no trailing newline).
4. `content_hash = "sha256:" + sha256(manifest-utf8)`.

### A.2 Capability and behavior

| Field | Req | Type | Notes |
| --- | --- | --- | --- |
| `description` | R | string | The exact SKILL.md triggering description, with negative triggers; this is what the Worker indexes. |
| `triggers.positive` | R | array of strings | When to use the skill. Target 10 or more in production cards. |
| `triggers.negative` | R | array | Each item is `{prompt, use_instead}` and names a sibling skill. Target 10 or more. |
| `inputs` | O | array | Input parameters or types. |
| `output.type` | R | string | For example Code, Markdown, JSON. |
| `output.format` | R | string | For example "Markdown with Python code blocks". |
| `dependencies` | R | array | Runtime libraries with versions, pip style. |
| `external_endpoints` | R | array or `"none"` | Enables a host-allowlist policy. |
| `permissions` | R | object | `{network, shell, file, env, mcp}`, each boolean, justified by the use case. |

The schema enforces a minimum of one positive and one negative trigger so the
worked example stays valid. The 10-or-more figure is the production target
described in section D, not a hard schema constraint.

### A.3 Quality scorecard

| Field | Req | Type | Notes |
| --- | --- | --- | --- |
| `metrics.trigger_precision` | R | 0.0 to 1.0 | TP / (TP + FP), mean of three runs. |
| `metrics.trigger_recall` | R | 0.0 to 1.0 | TP / (TP + FN), mean of three runs. |
| `metrics.near_miss_precision` | O | 0.0 to 1.0 | Precision on `triggers.negative`. |
| `metrics.task_completion_rate` | R | 0.0 to 1.0 | Graded pass over total functional tasks. |
| `metrics.tool_call_delta` | O | float | Change versus the no-skill baseline. |
| `metrics.token_efficiency` | O | float | Change versus the no-skill baseline. |
| `metrics.eval_pass_rate` | R | 0.0 to 1.0 | Functional eval pass rate. |
| `metrics.harness` | R | string | Format `skill-creator@<sha> / <model-id> / <date>`. |
| `metrics.notes` | O | string | Caveat on the scorecard: a number can be valid yet misleading (e.g. a harness-floor recall artifact). Added v2 (2026-06-19); nullable, omitted when absent. |

The individual fields above are required *within* a metrics block. The metrics
block as a whole is required only for `status: stable`; `draft`, `beta`, and
`deprecated` cards may omit it (lifecycle refinement, 2026-06-19), because the
eval harness that produces metrics is a v2 deliverable. The schema enforces the
metrics-for-stable rule.

### A.4 Security

| Field | Req | Type | Notes |
| --- | --- | --- | --- |
| `scan.tool` | R | string | Format `skillspector@<commit>`; pin the commit. |
| `scan.score` | R | 0 to 100 | Bands in section E. |
| `scan.severity` | R | enum | LOW, MEDIUM, HIGH, CRITICAL. |
| `scan.date` | R | ISO date | Should be 30 days old or less at release. |
| `scan.findings[]` | R | array | Each: `{rule_id, severity, status, owasp, atlas, note}`. |
| `scan.sarif` | R | path | Relative path to the SARIF report. |

Each finding: `status` is `resolved` or `accepted`. `owasp` carries the OWASP
ASI code and may be null (see the resolved item below). `atlas` carries the
MITRE ATLAS id and may be null. `note` justifies an accepted finding.

### A.5 Lifecycle

| Field | Req | Type | Notes |
| --- | --- | --- | --- |
| `status` | R | enum | draft, beta, stable, deprecated. |
| `card_version` | R | semver | The card schema version, for example 1.0. |
| `updated` | R | ISO date | Last update. |

The `scan.date` freshness rule (30 days or less) is a release-time policy, not
a schema validation, so that committed example cards do not expire.

---

## B. Worked example

The reference card is the `textual` skill. Its authored inputs are
[`examples/textual/SKILL.md`](examples/textual/SKILL.md) (identity) and
[`examples/textual/card.authored.yaml`](examples/textual/card.authored.yaml)
(governance); they generate the canonical
[`examples/textual/card.json`](examples/textual/card.json), which renders to the
[`examples/textual/skill-card.md`](examples/textual/skill-card.md) view. The test
suite regenerates `card.json` and `skill-card.md` byte for byte.

The trilogy (ratatui, bubbletea, textual) shares reference filenames and eval
ids, so cross-framework metric diffs become available once the harness writes
each `card.json`.

---

## C. Generator (`skillcard/`)

Execution chain:

```
skillcard optimize -> skillspector scan -> skillcard build -> skillcard review -> make check -> commit and tag
```

Module responsibilities:

| Module | Role | status (v0.4.0) |
| --- | --- | --- |
| `discover.py` | Walk a skill dir into a card context + per-field provenance: `SKILL.md` frontmatter (identity, hashed), the `card.authored.yaml` sidecar (governance overlay, not hashed), `.skillcard.toml` repo config, the SkillSpector JSON report (`report.json`/`scan.json`), `evals/evals.json` results, and git + hashing. | functional |
| `build_card.py` | Assemble and validate against `schema.py`; refuse on missing or mistyped required fields (including the sidecar-sourced `status`), naming them; write the canonical `card.json` plus its rendered `skill-card.md` view. One-way and idempotent. | functional |
| `render.py` | Render a card to `skill-card.md`: readable-YAML frontmatter (`yaml.safe_dump`) plus a Jinja body via `templates/skill-card.md.j2`. One-way; the md is never parsed back. | functional |
| `review.py` | Checklist of inferred-versus-HUMAN fields (`card-review.md`), fingerprint-bound to card.json; blocks `make check` until every HUMAN box is ticked. | functional |
| `gate.py` | SARIF and JSON security policy enforcement. | functional |
| `hashing.py` | `content_hash` over the skill's sorted source manifest. | functional |
| `harness/` | The harness `skillcard eval` and `skillcard optimize` run: namespace-isolated trigger runner (ported fork) + functional orchestrator (grades the on-disk artifact), assembled into `evals/evals.json`; plus the ported description optimizer (`optimize.py`). Live `claude`; never in `make check`. | functional |
| `badges.py` | Map `card.json` to shields.io endpoint JSON per metric. | stub |
| `cli.py` | The `skillcard` entrypoint: validate (canonical `card.json` schema + `content_hash`), gate, hash, build, review, eval, optimize; badges stub. | functional |
| `schema.py` (in `schema/`) | The pydantic model; single source of truth. | functional |

The generator runs after the description optimizer, so `description` and the
`metrics.trigger_*` values reflect the final optimized skill. The generator is
built in-house; it does not fork the NVIDIA generator and does not extend
skill-creator.

Determinism: `source_commit` and `updated` come from the last commit touching
the skill's *source* files (so committing the generated card never advances
them), or a `card.authored.yaml` pin for a self-contained fixture; `content_hash`
excludes the generated artifacts **and the governance sidecar**; `card.json` is
`json.dumps(indent=2)` in schema order. Because the sidecar is outside both the
hash manifest and the source-scoped commit, editing a governance field (status,
a finding decision) never moves `content_hash` or `source_commit` — only the
identity bytes in `SKILL.md` do. Re-running `skillcard build` on an unchanged
skill is byte-identical. The worked example in section B (`examples/textual/`) is
the in-repo regression gate: it carries its own source inputs and regenerates
byte for byte.

---

## D. Metrics computation

`skillcard eval <skill_dir>` runs the harness and writes the `results` block of
`<skill_dir>/evals/evals.json` that `discover.py` reads. It is a wrapper, not a
new runner: triggering reuses the **namespace-isolated fork** of skill-creator's
`run_eval` (ported into `skillcard/harness/`; the fix for the parallel
uuid-proxy contamination bug that produced false-low recall). Functional runs
each task's **full workflow to completion** -- the real skill plus the task
fixtures in an isolated workspace, `claude -p` with file-write permission -- and
grades the **on-disk artifact** the skill produces (the written `README.md`),
not the conversational `claude -p` stdout, with the skill's own deterministic
graders (`evals/functional/run_grader.py`). Grading the artifact rather than
stdout strips the model's wrapper prose -- an em-dash or AI-tell word in "here's
your README..." otherwise fails a check the README itself passes -- so the
functional numbers reproduce the cabinet's authoritative deterministic graders
rather than a depressed lower bound; if the skill writes no file the harness
falls back to extracting the artifact from stdout. The two sub-blocks are
written together or not at all (a `stable` card needs both; their absence is the
beta path). The residual gap to the authoritative score is single-shot generation
variance, so functional grading is **opt-in best-of-N** (`--best-of N`, default 1):
each task's generate -> grade cycle runs N times and the highest-scoring run is
kept, so a clean generation is what counts. `metrics.harness` records
`skill-eval-fork@<sha> / <model> / <date>`, with a trailing ` / best_of_<N>` when
N > 1 so a populated cert is transparent about how the number was obtained. The
output `evals/evals.json` is **excluded from `content_hash`** (it carries the
run's date, so hashing it would make the code identity non-deterministic across
runs); the authored eval *set* (`triggering.jsonl`, `functional/tasks.json`,
`run_grader.py`, `graders.py`, `fixtures/`) stays hashed as the test contract.
Real `claude` calls -> never part of `make check`; guarded behind an explicit
token-spend ack (N > 1 multiplies the cost, so it stays behind the same ack).

**Reliability (v0.6.2).** The harness keys on call FAILURES, not low scores: a
rate-limited / timed-out / errored `claude -p` call is tracked apart from a call
that completed without triggering, and excluded from the per-query denominators (a
failed call is not evidence the description failed to fire). If the call-failure
rate over a run reaches a conservative floor (0.2), the runner refuses the
measurement -- it raises and writes no `evals/evals.json` -- rather than record the
floor numbers a saturated run produces (recall ~0.14, etc.). The trigger eval is
**serial by default** (`--workers 1`); parallelism is opt-in (`--workers N`, faster
but able to saturate the account rate limit when nested in a session), which is the
saturation source the guard backstops. Both `eval` and `optimize` share this; a
low-but-honest score (calls succeed, grade low) still records normally.

**Rate-limit resilience (v0.7.0).** The harness drives the model by spawning the
`claude` CLI, so there is no in-process SDK whose retry/backoff we can configure --
the only seam is the subprocess boundary. Two layers live there. A client-side
token-bucket **pacer** (`--rate-limit`, requests/min, on at 40 by default; `0` opts
out) spaces call submission to stay under the account window -- the primary defense,
preventing the bursts rather than recovering from them. A **retry** wrapper
(`--max-retries`, default 4) retries a transient failure with exponential backoff and
jitter (`--backoff-base`/`--backoff-cap`), honoring a `retry-after` hint best-effort
when the CLI surfaces one; jitter shapes only the sleep, never the eval sampling. The
per-call timeout (`--timeout`) is decoupled from a new per-task wall-clock budget
(`--task-timeout`, default 900s) that bounds all of one call's retries. The v0.6.2
collapse guard is preserved but now keys on TERMINAL failures only: a call that
recovers on retry is a success and never trips the 0.2 abort, while a genuinely
saturated window (terminal failures climbing) still refuses. Each run records a
`reliability` provenance block (total retries, cumulative wait, max backoff, pacer
waits, terminal failures) in `evals/evals.json` and prints it, so a
throttled-but-recovered run is visible rather than silent. Harness + CLI behavior
only; `schema.py` stays frozen and `evals/evals.json` is still excluded from
`content_hash`, so the provenance never moves the code identity.

`skillcard optimize <skill_dir>` is the in-house description optimizer (the
ported skill-creator `run_loop`). It measures the current description against the
trigger eval set (`evals/triggering.jsonl`, or the inline `triggers:` block) on
the **same namespace-isolated runner** -- never skill-creator's un-forked
parallel eval -- asks `claude -p` to propose a better description that generalises
from the trigger failures, re-measures, and keeps the highest-scoring candidate.
Optimising the description legitimately moves `content_hash` (a real identity
change), so the write is always reviewed: it surfaces a unified diff and updates
`SKILL.md` only on accept (`--yes` to auto-accept, `--dry-run` to propose only).
Same token-spend ack; never part of `make check`.

- Triggering set: 10 or more positive and 10 or more negative examples drawn
  from `triggers.*`, each negative naming a sibling skill.
- Functional set: five to ten dossier tasks with assertion graders.

Formulas:

- `trigger_precision` = TP / (TP + FP); three runs per query, then the mean.
- `trigger_recall` = TP / (TP + FN); three runs per query, then the mean.
- `near_miss_precision` = 1 minus the over-trigger rate on `triggers.negative`.
- `task_completion_rate` = graded pass over total functional tasks.
- `tool_call_delta` and `token_efficiency` = change versus the no-skill
  baseline.

Re-run triggers: after each Claude model release, tracking deltas in a
CHANGELOG next to the `SKILL.md`. Re-optimize the description if
`trigger_recall` falls below about 0.7 or `task_completion_rate` regresses by
more than 10 percent.

---

## E. Scan gate (`make check`)

SkillSpector has no PyPI release. Install it with
`pip install git+https://github.com/NVIDIA/SkillSpector` (Python 3.12 to 3.14).
It emits SARIF 2.1.0 and covers a broad set of vulnerability patterns with an
OSV dependency lookup plus an offline fallback.

### Score model

SkillSpector computes the 0 to 100 score as: CRITICAL +50, HIGH +25,
MEDIUM +10, LOW +5 per finding, multiplied by 1.3 if the skill ships
executable scripts, then capped at 100. Bands:

| Score | Band |
| --- | --- |
| 0 to 20 | LOW |
| 21 to 50 | MEDIUM |
| 51 to 80 | HIGH |
| 81 to 100 | CRITICAL |

### Gate policy

| Score band | Outcome | Override |
| --- | --- | --- |
| 0 to 20 (LOW) | PASS | none needed |
| 21 to 50 (MEDIUM) | PASS only if every finding is `status: accepted` with a non-empty note on the card | no blank overrides |
| 51 to 80 (HIGH) | hard FAIL | none |
| 81 to 100 (CRITICAL) | hard FAIL | none |
| any CRITICAL-severity finding | hard FAIL regardless of total score | none |

Discipline: the gate does not blanket-reject `subprocess` or `shell` patterns.
The rule is "declared and justified in the card note equals accepted", not
"pattern present equals rejected". A Textual development skill legitimately runs
`textual run` and `pytest`.

Incremental adoption: a cabinet that is still carding its skills can gate
*every* skill on HIGH/CRITICAL while treating an as-yet-uncarded MEDIUM skill as
a warning, via `skillcard gate <report> --warn-medium-without-card`. The
HIGH/CRITICAL and CRITICAL-severity rules are never relaxed by that flag.

Modes: the static pass (`--no-llm`) is deterministic and belongs in the
blocking CI gate. The optional LLM semantic pass is non-deterministic, is for
pre-release only, and is never the CI gate.

### Where the gate reads the score (resolved)

The 0 to 100 score is not present in SkillSpector's SARIF output. The SARIF
result model is `{ruleId, message, level, locations}` only: no score, and a
lossy `level` where CRITICAL and HIGH both map to `error`. The score and the
exact per-finding severity live in SkillSpector's `--format json` report
(`risk_assessment.score`). Therefore `skillcard/gate.py` reads the JSON report
for its decision, and SARIF is produced separately for the GitHub code-scanning
upload. The CI recipe (section below) keeps the SARIF upload; `make check`
gates on the JSON.

### CI recipe (OWASP, drop-in)

```
setup-python 3.12
pip install git+https://github.com/NVIDIA/SkillSpector
skillspector scan ./skills --no-llm --format sarif --output skillspector.sarif
github/codeql-action/upload-sarif@v3   # needs permissions: security-events: write
```

See [`ci/skill-card-scan.yml`](ci/skill-card-scan.yml) for the reusable
template. `make check` runs the JSON gate plus ruff and pytest.

A note on self-scanning a framework repo: SkillSpector scans skills. Pointed at
this repo's whole tree it reads the Jinja template's permission tokens and the
pyproject's `requires-python` key as if they were a skill manifest and its
dependencies, which are false positives. The framework's own `make check`
therefore scans its shipping Python packages (`skillcard`, `schema`), which is
the real risk surface; a cabinet scanning its `skills/` directory does not have
this problem.

---

## F. Badges

Source: CI-fed shields.io `endpoint` JSON per metric, served from Cloudflare
Pages or R2. v1 uses static shields; v2 switches to endpoint badges.

Badge set: `scan` (severity band), `trigger` (precision and recall), `tasks`
(completion percent), `signed` (`hash+tag` or `oms`), `card` (card_version).

`badges.py` maps `card.json` to `{schemaVersion: 1, label, message, color}`
with one config dict for color thresholds. Shields requires every endpoint to
return HTTP 200. Badges read directly from `card.json`; there is no second
source of truth.

---

## G. Discover Worker contract

The `card.json` is the index payload. Most skills stay uninstalled, so an agent
queries for one to three relevant skills on demand and the always-loaded
metadata stays small, which mitigates the roughly 50-skill ceiling.

Storage: D1 for the catalog and structured filter, Vectorize for a semantic
embedding of `summary + description + triggers.positive`, R2 for the full card
and bundle. Not KV for the index.

Endpoints:

- `GET /discover?q=&tier=&max_scan=&k=` returns ranked minimal records with an
  install hint.
- `GET /card/<name>@<version>` returns the full card.
- `POST /ingest` is CI-fed with a bearer token and revalidates against
  `schema/schema.py`.
- `GET /badge/<name>/<metric>.json` returns shields.io endpoint JSON.

A tiny always-installed `discover` skill (about one slot) routes to the Worker.
Private cards require the bearer token and are never embedded in the public
Vectorize index. See [`worker/README.md`](worker/README.md).

---

## H. Phased roadmap

### v1 (weeks 1 to 2)

- Identity and provenance fields; `content_hash` over the sorted manifest.
- Clean SkillSpector `--no-llm` pass gated in `make check`.
- Hand-author cards for the top skills.
- CI fails on HIGH or CRITICAL findings.
- Flip threshold: if any skill scores HIGH on a non-overridable rule, fix the
  skill before anything else.

### v2 (weeks 3 to 6)

- Ship the full `skillcard/` generator (discover, build_card, render, review,
  gate, badges).
- Wire the skill-creator metrics harness.
- Stand up the discover Worker (D1, Vectorize, R2) plus the `discover` skill.
- Switch to endpoint badges.
- Build the Worker once the library crosses about 30 skills; do not wait for 50.

### v3 (week 7+)

- OMS Sigstore-keyless signing plus `model_signing verify` in CI.
- Add the `signature` field to the schema.
- Add a near-miss-precision merge gate.
- Private-repo proprietary license plus per-client signing.

---

## Resolved items

1. OWASP taxonomy for `scan.findings[].owasp`. SkillSpector emits OWASP ASI
   codes (for example `ASI02`, "Agent Security Initiative, Tool and Plugin
   Vulnerabilities") in each finding's tags, alongside MITRE ATLAS ids (for
   example `AML.T0080`). The `AST1` to `AST8` codes are SkillSpector's own
   behavioral-AST rule ids (exec, eval, subprocess, and so on), not an OWASP
   taxonomy; they live in `rule_id`. Decision: `owasp` carries the ASI code and
   is nullable (AST-only findings have no ASI mapping); `atlas` carries the
   ATLAS id; `rule_id` carries the SkillSpector rule.

2. SARIF score path. Resolved in section E: the score is not in SARIF; the gate
   reads the JSON report.

## Open items (for v2)

- The metrics *harness wrapper* -- **delivered in v0.5.0** as `skillcard eval`
  (SPEC §D), which ports the namespace-isolated `run_eval` fork and orchestrates
  the functional graders. Confirmed skill-creator script names against the
  installed plugin: `run_eval.py`, `run_loop.py`, `aggregate_benchmark.py`,
  `generate_report.py` (and `eval-viewer/generate_review.py`).
- The description optimizer (`run_loop`) -- **delivered in v0.6.0** as
  `skillcard optimize` (SPEC §C/§D): the loop is ported into `skillcard/harness/`
  on the same namespace-isolated runner (never skill-creator's un-forked parallel
  eval) and writes the proposed description to `SKILL.md` only on review. The same
  release re-pinned the functional axis to **artifact grading** (grade the
  produced `README.md`, not `claude -p` stdout), closing the lower-bound gap.
- Still open: the discover Worker.

## Locked decisions (2026-06-18; input layer refined 2026-06-19)

- Canonical format: authored `SKILL.md` frontmatter (identity, hashed) + a
  `card.authored.yaml` sidecar (governance, not hashed) generate the canonical
  `card.json`, which renders one-way to the `skill-card.md` view.
- Slug convention: kebab-case for the directory and `name`.
- Generator: built in-house; do not fork NVIDIA's generator or extend
  skill-creator.
- Scanning: SkillSpector static pass (`--no-llm`, SARIF 2.1.0) gated in
  `make check`.
- Signing: deferred to v3; v1 and v2 integrity is `content_hash` plus a signed
  git tag.
- v0.6.1 (2026-06-20): the metrics harness output `evals/evals.json` is excluded
  from `content_hash` (same class as `report.json`) so running `skillcard eval` —
  whose fresh date alone flips the hash — no longer moves the code identity; the
  authored eval set stays hashed as the test contract. Functional grading gains
  opt-in best-of-N (`--best-of N`, default 1 = single-shot) to reproduce the
  authoritative score by keeping the best of N generations per task; the sampling
  method is recorded in the `metrics.harness` string, never a new card field
  (`schema.py` is frozen).
- v0.6.2 (2026-06-21): the metrics harness refuses to record a floor-collapsed
  run. Call FAILURES (429 / timeout / errored `claude -p`) are tracked apart from
  completed non-triggers and, when their rate over a run reaches 0.2, the runner
  raises `EvalIntegrityError` and writes nothing -- a saturated run can no longer be
  mistaken for a real measurement, while a low-but-honest score still records. The
  trigger eval defaults to serial (`--workers 1`) with parallelism opt-in
  (`--workers N`) on both `eval` and `optimize`. Harness + CLI behavior only;
  `schema.py` stays frozen.
- v0.7.0 (2026-06-22): eval rate-limit resilience at the `claude` subprocess
  boundary (there is no in-process SDK to configure). A client-side token-bucket
  pacer (`--rate-limit` rpm, on at 40 by default; `0` disables) spaces call
  submission as the primary defense against sustained throttling; a retry wrapper
  (`--max-retries`, default 4) backs off exponentially with jitter
  (`--backoff-base`/`--backoff-cap`) and honors `retry-after` best-effort. The
  per-call `--timeout` is decoupled from a per-task wall-clock `--task-timeout`
  (default 900s) bounding all of one call's retries. The v0.6.2 collapse guard now
  keys on TERMINAL failures only -- a call recovered on retry counts as a success and
  does not trip the 0.2 abort, while a genuinely saturated window still refuses. Runs
  record a `reliability` provenance block (retries, cumulative wait, max backoff,
  pacer waits, terminal failures) in `evals/evals.json` (still excluded from
  `content_hash`). New module `skillcard/harness/reliability.py`; `eval` + `optimize`
  share the knobs. Harness + CLI behavior only; `schema.py` stays frozen.
