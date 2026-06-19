"""Califa Cards tooling package.

Functional modules:

* :mod:`skillcard.gate` -- the SkillSpector score gate used by ``make check``.
* :mod:`skillcard.hashing` -- the source ``content_hash``.
* :mod:`skillcard.discover` -- walk a skill dir into a card context.
* :mod:`skillcard.render` -- Jinja render of a card to ``skill-card.md``.
* :mod:`skillcard.build_card` -- validate, serialize, and write the card pair.
* :mod:`skillcard.review` -- the inferred-vs-HUMAN sign-off gate.
* :mod:`skillcard.cli` -- the ``skillcard`` entrypoint (validate, gate, hash,
  build, review; badges remains a v2 stub).

The deterministic generator (discover -> build -> render -> review) lands in
v0.3.0; see SPEC.md sections C and H. :mod:`skillcard.badges` is still a stub.
"""
