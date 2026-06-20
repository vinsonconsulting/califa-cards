"""Metrics harness for ``skillcard eval`` (SPEC.md section D).

Produces the ``evals/evals.json`` ``results`` block the generator consumes:

* :mod:`skillcard.harness.trigger` -- the namespace-isolated trigger runner,
  ported from the cabinet's ``tooling/skill-eval`` fork of skill-creator.
* :mod:`skillcard.harness.functional` -- the generate-then-grade functional
  orchestrator (net-new).
* :mod:`skillcard.harness.assemble` -- maps the runs to a generator-compatible
  ``results`` block (the specificity->near_miss_precision rename, both-blocks-or-none).
* :mod:`skillcard.harness.provenance` -- the ``metrics.harness`` string.

The runners make real ``claude -p`` calls; nothing here runs in ``make check``.
"""

from skillcard.harness.assemble import build_results_block, write_evals_json
from skillcard.harness.functional import run_functional
from skillcard.harness.provenance import harness_provenance
from skillcard.harness.trigger import (
    FORK_SHA,
    is_trigger,
    load_eval_set,
    make_isolated_workspace,
    parse_skill_md,
    run_eval,
)

__all__ = [
    "FORK_SHA",
    "build_results_block",
    "harness_provenance",
    "is_trigger",
    "load_eval_set",
    "make_isolated_workspace",
    "parse_skill_md",
    "run_eval",
    "run_functional",
    "write_evals_json",
]
