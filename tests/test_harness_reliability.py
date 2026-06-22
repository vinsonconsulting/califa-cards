"""v0.6.2 eval reliability guard: refuse floor-collapse runs, serial by default.

Offline (no ``claude`` calls): the trigger runner takes an injectable ``query_fn``
and the functional runner an injectable ``generate``, so the failure-tracking and
the refusal guard exercise real code paths with stub call results. The guard keys
on infrastructure CALL FAILURES (429 / timeout / errored ``claude -p``), never on a
low score, so a weak-but-honest skill still records.
"""

import json
import os

import pytest

from skillcard.harness.trigger import (
    CALL_FAILURE_ABORT_THRESHOLD,
    CallResult,
    EvalIntegrityError,
    guard_call_failures,
)

# --- the refusal helper: a high call-failure RATE raises; few/none records ---

def test_guard_raises_when_failure_rate_crosses_threshold():
    with pytest.raises(EvalIntegrityError):
        guard_call_failures(10, 10, CALL_FAILURE_ABORT_THRESHOLD, "trigger eval")


def test_guard_silent_below_threshold():
    # One failed call in twenty (5%) is below the 0.2 floor: a healthy run records.
    guard_call_failures(20, 1, CALL_FAILURE_ABORT_THRESHOLD, "trigger eval")


def test_guard_silent_when_no_calls_ran():
    # No calls at all is not a failure rate (0/0); never raise on an empty run.
    guard_call_failures(0, 0, CALL_FAILURE_ABORT_THRESHOLD, "trigger eval")


def test_guard_message_names_counts_and_remedy():
    with pytest.raises(EvalIntegrityError) as exc:
        guard_call_failures(7, 5, CALL_FAILURE_ABORT_THRESHOLD, "trigger eval")
    msg = str(exc.value)
    assert "5" in msg and "7" in msg and "--workers 1" in msg


# --- run_eval: serial by default, tracks call failures, refuses a saturated run ---

from skillcard.harness.trigger import run_eval  # noqa: E402


def _pos(q):
    return {"query": q, "should_trigger": True}


def _neg(q):
    return {"query": q, "should_trigger": False}


def test_run_eval_refuses_when_calls_saturate():
    # Every call fails (429/timeout-style) -> not a measurement -> raise, write nothing.
    eval_set = [_pos("p1"), _pos("p2")]
    qf = lambda *a: CallResult(triggered=False, failed=True)  # noqa: E731
    with pytest.raises(EvalIntegrityError):
        run_eval(eval_set, "demo", "d", num_workers=1, timeout=5,
                 runs_per_query=3, query_fn=qf)


def test_run_eval_records_low_score_without_failures():
    # Calls SUCCEED but the skill triggers poorly: a low-but-honest score records
    # normally (no false positive on the failure guard).
    eval_set = [_pos("p1"), _pos("p2"), _neg("n1")]

    def qf(query, *a):
        triggered = query == "p1"  # p1 fires, p2 never, n1 never
        return CallResult(triggered=triggered, failed=False)

    out = run_eval(eval_set, "demo", "d", num_workers=1, timeout=5,
                   runs_per_query=2, query_fn=qf)
    s = out["summary"]
    assert s["calls_failed"] == 0
    assert s["calls_total"] == 6
    assert s["recall"] == 0.5      # p1 2/2, p2 0/2 -> 2/4
    assert s["precision"] == 1.0   # no false triggers
    assert s["specificity"] == 1.0


def test_run_eval_default_is_in_process_serial():
    # num_workers=1 runs every call in THIS process (no ProcessPoolExecutor fan-out).
    pids = []

    def qf(*a):
        pids.append(os.getpid())
        return CallResult(triggered=False, failed=False)

    run_eval([_pos("p1")], "demo", "d", num_workers=1, timeout=5,
             runs_per_query=2, query_fn=qf)
    assert pids == [os.getpid(), os.getpid()]


def test_run_eval_all_runs_failed_no_zero_division():
    # A query whose every run failed has zero successful calls; with the guard
    # disabled (high threshold) the aggregation must not divide by zero.
    qf = lambda *a: CallResult(triggered=False, failed=True)  # noqa: E731
    out = run_eval([_pos("p1")], "demo", "d", num_workers=1, timeout=5,
                   runs_per_query=2, query_fn=qf, failure_threshold=2.0)
    s = out["summary"]
    assert s["calls_failed"] == 2 and s["calls_total"] == 2
    # No successful runs for the query -> runs 0, no ZeroDivisionError; recall None.
    assert out["results"][0]["runs"] == 0
    assert s["recall"] is None


# --- _StreamDecider: the poll-break fix -- a buffered terminal event still decides ---

def test_stream_decider_parses_buffered_assistant_tool_use():
    from skillcard.harness.trigger import _StreamDecider

    d = _StreamDecider("github-readme")
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Skill",
             "input": {"skill": "github-readme-skill-aaaa1111"}},
        ]},
    })
    decision, remaining = d.feed(line + "\n")
    assert decision is True
    assert remaining == ""


def test_stream_decider_message_stop_is_clean_miss_not_failure():
    from skillcard.harness.trigger import _StreamDecider

    d = _StreamDecider("github-readme")
    line = json.dumps({"type": "stream_event", "event": {"type": "message_stop"}})
    decision, _ = d.feed(line + "\n")
    assert decision is False  # ran to completion, never triggered -> a miss


def test_stream_decider_partial_line_needs_more_data():
    from skillcard.harness.trigger import _StreamDecider

    d = _StreamDecider("github-readme")
    decision, remaining = d.feed('{"type": "assistant"')
    assert decision is None
    assert remaining == '{"type": "assistant"'


# --- functional runner: track generation failures, refuse a saturated run ---

from skillcard.harness import run_functional  # noqa: E402
from skillcard.harness.functional import EvalCallError  # noqa: E402

_GRADERS = '''
def grade(task_id, text, cfg):
    exps = [{"text": "has hello", "passed": "hello" in text, "evidence": ""}]
    passed = sum(1 for e in exps if e["passed"])
    return {"expectations": exps,
            "summary": {"passed": passed, "total": len(exps), "pass_rate": passed / len(exps)}}
'''

_RUN_GRADER = '''
import argparse, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import graders

def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--task"); ap.add_argument("--readme"); ap.add_argument("--out")
    a = ap.parse_args(argv)
    text = Path(a.readme).read_text()
    result = graders.grade(a.task, text, {})
    Path(a.out).write_text(json.dumps(result))
    s = result["summary"]
    return 0 if s["passed"] == s["total"] else 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def _make_multitask_skill(tmp_path, n_tasks):
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n# demo\n")
    func = skill / "evals" / "functional"
    func.mkdir(parents=True)
    tasks = [{"id": f"t{i}", "name": f"t{i}", "prompt": "write hello",
              "fixtures": [], "grader_config": {}} for i in range(n_tasks)]
    (func / "tasks.json").write_text(json.dumps({"skill_name": "demo", "tasks": tasks}))
    (func / "graders.py").write_text(_GRADERS)
    (func / "run_grader.py").write_text(_RUN_GRADER)
    return skill


def test_run_functional_refuses_when_generations_saturate(tmp_path):
    # Every task generation fails (timeout / 429) -> not a measurement -> raise.
    skill = _make_multitask_skill(tmp_path, 4)

    def generate(task):
        raise EvalCallError("simulated rate-limit")

    with pytest.raises(EvalIntegrityError):
        run_functional(skill, generate=generate)


def test_run_functional_one_failure_below_threshold_records(tmp_path):
    # One generation of six fails (16% < 20% floor): the run records, and the failed
    # task contributes 0.0 instead of crashing on a None "best".
    skill = _make_multitask_skill(tmp_path, 6)

    def generate(task):
        if task["id"] == "t0":
            raise EvalCallError("one flaky generation")
        return "hello"

    out = run_functional(skill, generate=generate)
    assert out["calls_failed"] == 1
    assert out["calls_total"] == 6
    assert out["task_completion_rate"] == pytest.approx(5 / 6)
    assert out["eval_pass_rate"] == pytest.approx(5 / 6)


# --- command level: refuse-and-write-nothing vs record-low-but-valid ---

import argparse  # noqa: E402

from skillcard.harness.command import run_eval_command  # noqa: E402


def _eval_args(skill_dir, **over):
    base = dict(ack=True, best_of=1, skill_dir=str(skill_dir), workers=1,
                runs_per_query=2, timeout=5, model="m", workspace_base=None,
                skip_functional=False, out=None)
    base.update(over)
    return argparse.Namespace(**base)


def _skill_with_triggering(tmp_path):
    skill = tmp_path / "demo"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n# demo\n")
    (skill / "evals" / "triggering.jsonl").write_text(
        '{"query": "p1", "should_trigger": true}\n'
        '{"query": "n1", "should_trigger": false}\n'
    )
    return skill


def test_eval_command_refuses_and_writes_nothing(tmp_path, monkeypatch):
    skill = _skill_with_triggering(tmp_path)
    sentinel = skill / "evals" / "evals.json"
    sentinel.write_text('{"skill_name": "demo", "evals": ["KEEP"]}')
    before = sentinel.read_bytes()

    import skillcard.harness.command as command
    import skillcard.harness.trigger as trigger
    monkeypatch.setattr(command.shutil, "which", lambda _x: "/usr/bin/claude")
    monkeypatch.setattr(trigger, "run_single_query",
                        lambda *a: CallResult(triggered=False, failed=True))

    with pytest.raises(EvalIntegrityError):
        run_eval_command(_eval_args(skill))
    # Nothing written: the pre-existing evals.json is byte-identical.
    assert sentinel.read_bytes() == before


def test_eval_command_records_low_but_valid_run(tmp_path, monkeypatch):
    skill = _skill_with_triggering(tmp_path)

    import skillcard.harness.command as command
    import skillcard.harness.trigger as trigger
    monkeypatch.setattr(command.shutil, "which", lambda _x: "/usr/bin/claude")
    # Calls SUCCEED (no failures) but never trigger -> a low, honest score.
    monkeypatch.setattr(trigger, "run_single_query",
                        lambda *a: CallResult(triggered=False, failed=False))
    monkeypatch.setattr(command, "run_functional", lambda *a, **k: {
        "eval_pass_rate": 0.42, "task_completion_rate": 0.14,
        "tasks_passed": "1/7", "per_task": [], "calls_total": 7, "calls_failed": 0,
    })

    code = run_eval_command(_eval_args(skill))
    assert code == 0
    written = json.loads((skill / "evals" / "evals.json").read_text())
    assert written["results"]["functional"]["eval_pass_rate"] == 0.42
    assert written["results"]["triggering"]["recall"] == 0.0


def test_eval_integrity_error_exported_from_harness():
    from skillcard.harness import EvalIntegrityError as Exported
    assert Exported is EvalIntegrityError


# --- CLI: --workers is serial (1) by default; parallelism is opt-in ---

def _capture_workers(monkeypatch, target):
    captured = {}
    monkeypatch.setattr(target, lambda args: captured.update(workers=args.workers) or 0)
    return captured


def test_eval_workers_defaults_to_serial(monkeypatch):
    import skillcard.cli as cli
    cap = _capture_workers(monkeypatch, "skillcard.harness.command.run_eval_command")
    cli.main(["eval", "skills/x", "--i-understand-this-spends-tokens"])
    assert cap["workers"] == 1


def test_eval_workers_opt_in_parallel(monkeypatch):
    import skillcard.cli as cli
    cap = _capture_workers(monkeypatch, "skillcard.harness.command.run_eval_command")
    cli.main(["eval", "skills/x", "--workers", "4", "--i-understand-this-spends-tokens"])
    assert cap["workers"] == 4


def test_optimize_workers_defaults_to_serial(monkeypatch):
    import skillcard.cli as cli
    cap = _capture_workers(monkeypatch, "skillcard.harness.optimize.run_optimize_command")
    cli.main(["optimize", "skills/x", "--i-understand-this-spends-tokens"])
    assert cap["workers"] == 1


# --- optimize: a saturated measurement is a clean FAIL, not a raw traceback ---

def test_optimize_command_clean_fail_on_saturation(tmp_path, monkeypatch):
    skill = tmp_path / "demo"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n# demo\n")

    import skillcard.harness.optimize as optimize
    monkeypatch.setattr(optimize.shutil, "which", lambda _x: "/usr/bin/claude")

    def boom(*a, **k):
        raise EvalIntegrityError("3 of 4 trigger eval calls failed -- --workers 1")

    monkeypatch.setattr(optimize, "run_optimize", boom)
    args = argparse.Namespace(
        ack=True, skill_dir=str(skill), model="m", workers=1, timeout=5,
        runs_per_query=3, max_iterations=3, yes=False, dry_run=False,
        workspace_base=None,
    )
    assert optimize.run_optimize_command(args) == 1


# --- v0.7.0 functional retry: a recovered generation is a success, not a failure ---


def test_functional_retry_recovers_without_tripping_guard(tmp_path):
    # Each task's generation fails once then succeeds. With retries the run records
    # cleanly and the collapse guard does NOT trip -- the failures were transient and
    # the retry layer handled them, so they must not count toward the 0.2 abort.
    skill = _make_multitask_skill(tmp_path, 4)
    attempts: dict[str, int] = {}

    def generate(task):
        n = attempts.get(task["id"], 0) + 1
        attempts[task["id"]] = n
        if n == 1:
            raise EvalCallError("transient 429")
        return "hello"

    out = run_functional(skill, generate=generate, max_retries=3, sleep=lambda s: None)
    assert out["calls_failed"] == 0                 # recovered -> no terminal failures
    assert out["calls_total"] == 4
    assert out["task_completion_rate"] == 1.0
    assert out["reliability"]["total_retries"] == 4  # exactly one retry per task
    assert out["reliability"]["terminal_failures"] == 0


def test_functional_terminal_failures_still_trip_guard(tmp_path):
    # Generations never recover: even with retries every task fails terminally, so the
    # saturated run is still refused (terminal failures DO count toward the guard).
    skill = _make_multitask_skill(tmp_path, 4)

    def generate(task):
        raise EvalCallError("hard saturation")

    with pytest.raises(EvalIntegrityError):
        run_functional(skill, generate=generate, max_retries=2, sleep=lambda s: None)


def test_functional_reliability_block_present_by_default(tmp_path):
    skill = _make_multitask_skill(tmp_path, 2)
    out = run_functional(skill, generate=lambda t: "hello")
    assert set(out["reliability"]) >= {
        "total_retries", "terminal_failures", "pacer_wait_count", "max_backoff_s",
    }
    assert out["reliability"]["terminal_failures"] == 0


# --- v0.7.0 trigger retry: a recovered call is a success, not a guard failure ---


def test_run_eval_retry_recovers_call_without_counting_failure():
    # p1's first run fails (429-style) then succeeds: with retries it records as a
    # clean trigger and contributes nothing to the call-failure guard.
    seen: dict[str, int] = {}

    def qf(query, *a):
        n = seen.get(query, 0) + 1
        seen[query] = n
        if n == 1:
            return CallResult(triggered=False, failed=True)   # transient
        return CallResult(triggered=True, failed=False)       # recovers on retry

    out = run_eval([_pos("p1")], "demo", "d", num_workers=1, timeout=5,
                   runs_per_query=1, query_fn=qf, max_retries=3, sleep=lambda s: None)
    s = out["summary"]
    assert s["calls_failed"] == 0
    assert s["calls_total"] == 1
    assert s["recall"] == 1.0
    assert s["reliability"]["total_retries"] == 1
    assert s["reliability"]["terminal_failures"] == 0


def test_run_eval_terminal_failures_still_refuse():
    # Every call fails terminally even after retries -> saturated -> raise.
    qf = lambda *a: CallResult(triggered=False, failed=True)  # noqa: E731
    with pytest.raises(EvalIntegrityError):
        run_eval([_pos("p1"), _pos("p2")], "demo", "d", num_workers=1, timeout=5,
                 runs_per_query=3, query_fn=qf, max_retries=2, sleep=lambda s: None)


def test_run_eval_reliability_in_summary_by_default():
    qf = lambda *a: CallResult(triggered=True, failed=False)  # noqa: E731
    out = run_eval([_pos("p1")], "demo", "d", num_workers=1, timeout=5,
                   runs_per_query=1, query_fn=qf)
    assert out["summary"]["reliability"]["terminal_failures"] == 0
    assert out["summary"]["reliability"]["total_retries"] == 0


def test_eval_command_writes_merged_reliability_block(tmp_path, monkeypatch):
    # The command surfaces the run's resilience stats in evals.json: trigger +
    # functional reliability merged into results.reliability.
    skill = _skill_with_triggering(tmp_path)

    import skillcard.harness.command as command
    import skillcard.harness.trigger as trigger
    monkeypatch.setattr(command.shutil, "which", lambda _x: "/usr/bin/claude")
    monkeypatch.setattr(trigger, "run_single_query",
                        lambda *a: CallResult(triggered=True, failed=False))
    monkeypatch.setattr(command, "run_functional", lambda *a, **k: {
        "eval_pass_rate": 1.0, "task_completion_rate": 1.0, "tasks_passed": "1/1",
        "per_task": [], "calls_total": 1, "calls_failed": 0,
        "reliability": {"total_retries": 2, "cumulative_wait_s": 1.0,
                        "max_backoff_s": 1.0, "pacer_wait_count": 0,
                        "pacer_wait_s": 0.0, "terminal_failures": 0},
    })

    assert run_eval_command(_eval_args(skill)) == 0
    written = json.loads((skill / "evals" / "evals.json").read_text())
    rel = written["results"]["reliability"]
    assert rel["total_retries"] == 2          # trigger 0 + functional 2
    assert rel["terminal_failures"] == 0
