"""Regression guard for the parallel uuid-proxy contamination fix (ported).

Pins the INVARIANTS of the namespace-isolation fix, WITHOUT invoking ``claude``
(no API cost, deterministic in CI). Ported from the cabinet fork's
``tooling/skill-eval/tests/test_isolation.py`` -- only the import changes, since
the runner now lives in the ``skillcard.harness`` package.
"""

import shutil
import uuid
from pathlib import Path

import pytest

from skillcard.harness import trigger as run_eval


@pytest.fixture
def home_tmp():
    """A scratch dir UNDER ~/ (never /tmp), per the workspace convention."""
    base = Path.home() / ".cache" / "skill-eval-workspaces-test" / uuid.uuid4().hex[:8]
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_default_workspace_root_is_under_home_not_tmp():
    root = str(run_eval.EVAL_WORKSPACE_ROOT)
    assert root.startswith(str(Path.home())), root
    assert "/tmp" not in root, root


def test_isolation_workspaces_do_not_share_namespace(home_tmp):
    mk = run_eval.make_isolated_workspace
    wd_a, _proxy_a, name_a = mk("github-readme", "desc A", base=home_tmp)
    wd_b, _proxy_b, name_b = mk("github-readme", "desc B", base=home_tmp)

    assert name_a != name_b
    assert wd_a != wd_b

    a_files = {p.name for p in (wd_a / ".claude" / "commands").iterdir()}
    b_files = {p.name for p in (wd_b / ".claude" / "commands").iterdir()}

    # Each workspace contains ONLY its own proxy ...
    assert a_files == {f"{name_a}.md"}
    assert b_files == {f"{name_b}.md"}
    # ... so worker A can never observe worker B's sibling proxy (the bug's cause).
    assert f"{name_b}.md" not in a_files
    assert str(wd_a).startswith(str(Path.home()))


def test_is_trigger_credits_own_and_sibling_same_skill_proxy():
    skill = "github-readme"
    own = "github-readme-skill-aaaa1111"
    sibling = "github-readme-skill-bbbb2222"

    assert run_eval.is_trigger("Skill", own, skill) is True
    # Sibling SAME-skill proxy -> hit. The exact case the buggy harness mis-scored.
    assert run_eval.is_trigger("Skill", sibling, skill) is True
    assert run_eval.is_trigger("Read", f"/x/.claude/commands/{sibling}.md", skill) is True
    # A DIFFERENT skill's proxy -> miss (no cross-credit between skills).
    assert run_eval.is_trigger("Skill", "github-action-skill-cccc3333", skill) is False
    assert run_eval.is_trigger("Bash", "ls -la", skill) is False


def test_load_eval_set_reads_jsonl(home_tmp):
    p = home_tmp / "triggering.jsonl"
    p.write_text(
        '{"query": "a", "should_trigger": true}\n'
        '\n'
        '{"query": "b", "should_trigger": false}\n'
    )
    assert run_eval.load_eval_set(p) == [
        {"query": "a", "should_trigger": True},
        {"query": "b", "should_trigger": False},
    ]


def test_load_eval_set_reads_json_array(home_tmp):
    p = home_tmp / "evals.json"
    p.write_text('[{"query": "a", "should_trigger": true}]')
    assert run_eval.load_eval_set(p) == [{"query": "a", "should_trigger": True}]
