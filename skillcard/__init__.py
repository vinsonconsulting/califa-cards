"""Califa Cards tooling package.

Functional modules:

* :mod:`skillcard.gate` -- the SkillSpector score gate used by ``make check``.
* :mod:`skillcard.hashing` -- the source ``content_hash``.
* :mod:`skillcard.discover` -- walk a skill dir into a card context.
* :mod:`skillcard.render` -- render a card to ``skill-card.md`` (readable-YAML
  frontmatter + Jinja body); one-way, the view is never parsed back.
* :mod:`skillcard.build_card` -- validate, serialize the canonical ``card.json``,
  and render its view.
* :mod:`skillcard.review` -- the inferred-vs-HUMAN sign-off gate.
* :mod:`skillcard.harness` -- the metrics harness behind ``skillcard eval``: a
  namespace-isolated trigger runner (ported fork) + functional grader
  orchestrator that writes ``evals/evals.json``. Makes real ``claude`` calls; it
  is never exercised by ``make check``.
* :mod:`skillcard.cli` -- the ``skillcard`` entrypoint (validate, gate, hash,
  build, review, eval; badges remains a v2 stub).

The deterministic generator (discover -> build -> render -> review) landed in
v0.3.0; v0.4.0 moved authored governance to a ``card.authored.yaml`` sidecar so
it no longer affects ``content_hash``; v0.5.0 added the ``eval`` metrics harness.
See SPEC.md sections C, D, and H. :mod:`skillcard.badges` is still a stub.
"""
