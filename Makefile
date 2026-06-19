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

ifeq ($(wildcard $(VENV)/bin/python),)
  PYBIN := $(PY)
  BINPREFIX :=
else
  PYBIN := $(VENV)/bin/python
  BINPREFIX := $(VENV)/bin/
endif

.PHONY: dev lint test scan check clean

dev:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -e ".[dev,scan]"

lint:
	$(BINPREFIX)ruff check .

test:
	$(PYBIN) -m pytest -q

scan:
	@for tgt in $(SCAN_TARGETS); do \
		echo ">> skillspector scan $$tgt"; \
		$(BINPREFIX)skillspector scan $$tgt --no-llm --format json --output report.json; \
		$(BINPREFIX)skillspector scan $$tgt --no-llm --format sarif --output report.sarif; \
		$(PYBIN) -m skillcard.gate report.json || exit 1; \
	done

check: lint test scan

clean:
	rm -rf $(VENV) report.json report.sarif .pytest_cache .ruff_cache *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
