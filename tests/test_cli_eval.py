"""`skillcard eval` sequencing guard: no token spend without the explicit ack.

The ack check short-circuits before any ``claude`` call, so `make check` / CI can
never accidentally spend tokens by invoking the subcommand.
"""

from skillcard import cli


def test_eval_without_ack_exits_2_and_spends_nothing():
    # No --i-understand-this-spends-tokens -> exit 2 before any harness call.
    assert cli.main(["eval", "/nonexistent-skill-dir"]) == 2


def test_eval_with_ack_but_missing_eval_set_fails_cleanly(tmp_path):
    # Past the ack + claude-present checks, a skill with no triggering.jsonl is a
    # clean exit 1 (not a traceback). claude is on PATH locally; if absent the
    # earlier claude-check returns 1 too, so the assertion holds either way.
    (tmp_path / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n")
    code = cli.main(["eval", str(tmp_path), "--i-understand-this-spends-tokens"])
    assert code == 1
