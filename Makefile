# Califa Cards build gate.
#
#   make dev     create .venv and install the package with dev + scan extras
#   make check   the full gate: ruff lint + pytest + a clean SkillSpector self-scan
#   make lint / make test / make scan   run a single stage
#
# `make check` uses .venv when present (after `make dev`) and otherwise falls
# back to whatever python3 / ruff / skillspector are on PATH, so the same
# target works locally and in CI.
#
# The self-scan targets the shipping Python packages (skillcard, schema), not
# the whole tree. SkillSpector scans *skills*: pointed at a framework repo it
# reads the Jinja template's permission tokens and the pyproject as if they
# were a skill manifest and its dependencies, which are false positives. The
# real risk surface is the code we ship and run. SkillSpector takes one path
# per invocation, so the scan target loops.

PY ?= python3
VENV := .venv
SCAN_TARGETS ?= skillcard schema
# Carded skill dirs whose generated cards must have signed-off HUMAN fields.
REVIEW_TARGETS ?= examples/textual

ifeq ($(wildcard $(VENV)/bin/python),)
  PYBIN := $(PY)
  BINPREFIX :=
else
  PYBIN := $(VENV)/bin/python
  BINPREFIX := $(VENV)/bin/
endif

.PHONY: dev lint test scan review eval check clean

EVAL_WORKERS ?= 1

dev:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -e ".[dev,scan]"

lint:
	$(BINPREFIX)ruff check .

test:
	$(PYBIN) -m pytest -q

# The eval harness (skillcard/harness/) drives `claude` and writes proxy command
# files by design, so SkillSpector reads it as skill-manifest manipulation -- a
# false positive on framework tooling (the cabinets keep their skill-eval fork
# out of scan for the same reason). Scan a staged copy with the harness pruned.
scan:
	@rm -rf .scan-stage && mkdir -p .scan-stage
	@for tgt in $(SCAN_TARGETS); do cp -R $$tgt .scan-stage/$$tgt; done
	@rm -rf .scan-stage/skillcard/harness
	@for tgt in $(SCAN_TARGETS); do \
		echo ">> skillspector scan $$tgt (eval harness excluded)"; \
		$(BINPREFIX)skillspector scan .scan-stage/$$tgt --no-llm --format json --output report.json; \
		$(BINPREFIX)skillspector scan .scan-stage/$$tgt --no-llm --format sarif --output report.sarif; \
		$(PYBIN) -m skillcard.gate report.json || { rm -rf .scan-stage; exit 1; }; \
	done
	@rm -rf .scan-stage

review:
	@for tgt in $(REVIEW_TARGETS); do \
		echo ">> skillcard review $$tgt"; \
		$(PYBIN) -m skillcard.cli review $$tgt || exit 1; \
	done

# Run the metrics harness for one skill: triggering + functional evals -> evals.json.
# Usage: make eval SKILL=examples/textual [EVAL_WORKERS=N]  (serial by default)
# Needs the `claude` CLI (real API calls, spends tokens); intentionally NOT in `check`.
eval:
	$(PYBIN) -m skillcard.cli eval $(SKILL) --workers $(EVAL_WORKERS) \
		--i-understand-this-spends-tokens

check: lint test scan review

clean:
	rm -rf $(VENV) report.json report.sarif .scan-stage .pytest_cache .ruff_cache *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
