# discover Worker (design, v2)

The discover Worker is the query surface for the skill library. It exists
because most skills stay uninstalled: an agent should be able to ask for the
one to three skills relevant to a task on demand, rather than carrying every
skill's metadata in context. That keeps the always-loaded footprint small and
sidesteps the roughly 50-skill ceiling. This directory is a design stub for v2;
no Worker is deployed in v0.

SPEC.md section G is the normative contract. This README is the implementation
sketch.

## Storage

The `card.json` produced by Califa Cards is itself the index payload. No second
source of truth.

- **D1** holds the catalog and structured filter columns (name, version, tier,
  status, scan severity, license).
- **Vectorize** holds a semantic embedding of `summary + description +
  triggers.positive` for relevance ranking.
- **R2** holds the full card and any bundle.
- Not KV for the index.

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /discover?q=&tier=&max_scan=&k=` | ranked minimal records with an `install` hint |
| `GET /card/<name>@<version>` | the full card |
| `POST /ingest` | CI-fed; bearer token; validates against `schema/schema.py` before writing |
| `GET /badge/<name>/<metric>.json` | shields.io endpoint JSON (section F) |

## Ingest validation

`POST /ingest` revalidates every incoming card against the same
`schema.schema.SkillCard` the cabinets' `make check` uses. The schema is the
shared contract between author-time validation and index-time validation, so a
card that passes locally cannot be rejected at ingest for a shape reason, and a
malformed card cannot enter the index.

## Privacy

Private cards require the bearer token and are never embedded in the public
Vectorize index. The public surface only ever returns public-tier cards.

## Build trigger

Stand the Worker up once the library crosses roughly 30 skills; do not wait for
50. See SPEC.md section H.
