"""Assembly contract: a harness run -> the generator's evals.json results block.

Pins the two invariants the wrapper exists to enforce: the
``specificity -> near_miss_precision`` rename, and ``both-blocks-or-none`` (a
triggering-only block would crash ``build_card``, so it is never written). The
final test closes the loop through the real consumer, ``discover._metrics``.
"""

import json

from skillcard.discover import _metrics
from skillcard.harness import build_results_block, harness_provenance, write_evals_json
from skillcard.harness.trigger import FORK_SHA


def _trig(precision=1.0, recall=0.6944, specificity=1.0):
    return {"summary": {"precision": precision, "recall": recall, "specificity": specificity,
                        "total": 24, "passed": 20, "failed": 4}}


_FUNC = {"eval_pass_rate": 1.0, "task_completion_rate": 1.0}


def test_specificity_is_renamed_to_near_miss_precision():
    block = build_results_block(_trig(), _FUNC, "m", "2026-06-20")
    assert block["triggering"]["near_miss_precision"] == 1.0
    assert "specificity" not in block["triggering"]


def test_precision_recall_passthrough_and_rounding():
    block = build_results_block(_trig(precision=0.95123, recall=0.881111),
                                {"eval_pass_rate": 0.86111, "task_completion_rate": 0.8333},
                                "m", "2026-06-20")
    assert block["triggering"]["precision"] == 0.9512
    assert block["triggering"]["recall"] == 0.8811
    assert block["functional"]["eval_pass_rate"] == 0.8611


def test_none_recall_is_preserved_not_rounded():
    block = build_results_block(_trig(recall=None), _FUNC, "m", "d")
    assert block["triggering"]["recall"] is None


def test_no_functional_means_no_results_block_beta_path():
    assert build_results_block(_trig(), None, "m", "d") is None


def test_provenance_format():
    block = build_results_block(_trig(), _FUNC, "claude-opus-4-8", "2026-06-20")
    assert block["date"] == "2026-06-20"
    assert block["harness"] == f"skill-eval-fork@{FORK_SHA} / claude-opus-4-8 / 2026-06-20"
    assert harness_provenance("m", "d", sha="abc123") == "skill-eval-fork@abc123 / m / d"


def test_write_evals_json_preserves_eval_defs(tmp_path):
    evals = tmp_path / "evals"
    evals.mkdir()
    prior = {"skill_name": "demo", "evals": [{"id": 1, "prompt": "p", "rubric": ["x"]}]}
    (evals / "evals.json").write_text(json.dumps(prior), encoding="utf-8")
    write_evals_json(tmp_path, evals, "demo", _trig(), _FUNC, "m", "2026-06-20")
    data = json.loads((evals / "evals.json").read_text(encoding="utf-8"))
    assert data["evals"] == prior["evals"]  # authored defs carried through verbatim
    assert "results" in data


def test_results_block_populates_discover_metrics(tmp_path):
    # The end-to-end contract: write a block, then read it via the real consumer.
    evals = tmp_path / "evals"
    evals.mkdir()
    write_evals_json(tmp_path, evals, "demo", _trig(recall=0.69), _FUNC, "m", "2026-06-20")
    m = _metrics(tmp_path, {})
    assert m is not None
    assert m["trigger_recall"] == 0.69
    assert m["near_miss_precision"] == 1.0
    assert m["eval_pass_rate"] == 1.0 and m["task_completion_rate"] == 1.0
    assert m["harness"].startswith("skill-eval-fork@")


def test_no_results_block_is_discover_beta_none(tmp_path):
    evals = tmp_path / "evals"
    evals.mkdir()
    write_evals_json(tmp_path, evals, "demo", _trig(), None, "m", "2026-06-20")
    assert _metrics(tmp_path, {}) is None  # beta path, never a half-populated dict


def test_textual_offline_parity_with_committed_results():
    # The textual offline demonstration (no live claude): the wrapper, fed the
    # textual scorecard numbers, reproduces the committed results sub-blocks
    # exactly (only harness/date differ). The committed fixture is never touched.
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    fixture = repo / "examples" / "textual" / "evals" / "evals.json"
    committed = json.loads(fixture.read_text())["results"]
    trig = {"summary": {"precision": committed["triggering"]["precision"],
                        "recall": committed["triggering"]["recall"],
                        "specificity": committed["triggering"]["near_miss_precision"]}}
    func = {"eval_pass_rate": committed["functional"]["eval_pass_rate"],
            "task_completion_rate": committed["functional"]["task_completion_rate"]}
    block = build_results_block(trig, func, "claude-opus-4-8", "2026-06-17")
    assert block["triggering"] == committed["triggering"]
    assert block["functional"] == committed["functional"]
