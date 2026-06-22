"""Hashing tests: generated/scan artifacts never enter the content_hash."""

from __future__ import annotations

from skillcard.hashing import content_hash


def test_scan_report_artifacts_excluded(tmp_path):
    # content_hash describes *source*. A transient SkillSpector report dropped
    # next to the source by `make scan` (report.json) must not change the hash,
    # exactly as scan.json / report.sarif already do not.
    (tmp_path / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    before = content_hash(tmp_path)

    (tmp_path / "report.json").write_text('{"risk_assessment": {"score": 0}}', encoding="utf-8")
    (tmp_path / "scan.json").write_text('{"risk_assessment": {"score": 0}}', encoding="utf-8")
    (tmp_path / "report.sarif").write_text("{}", encoding="utf-8")
    # The generated card and its review checklist are excluded too.
    (tmp_path / "card.json").write_text("{}", encoding="utf-8")
    (tmp_path / "skill-card.md").write_text("---\n---\n", encoding="utf-8")
    # README.md is a rendered doc view (a cabinet's README cascade), excluded like skill-card.md.
    (tmp_path / "README.md").write_text("# demo skill\n", encoding="utf-8")
    (tmp_path / "card-review.md").write_text("# review\n", encoding="utf-8")
    # The authored governance sidecar is excluded: status/finding decisions are
    # overlay data, not the code the hash describes.
    (tmp_path / "card.authored.yaml").write_text("status: beta\n", encoding="utf-8")

    assert content_hash(tmp_path) == before


def test_eval_output_excluded_but_eval_set_hashed(tmp_path):
    # `evals/evals.json` is harness *output*: `skillcard eval` rewrites it with a
    # fresh date plus a results block. Like report.json, it must not move the
    # code-identity hash -- while the authored eval *set* (the test contract) must.
    (tmp_path / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    evals = tmp_path / "evals"
    func = evals / "functional"
    func.mkdir(parents=True)
    # The authored eval set: trigger queries + dossier tasks + the grader.
    (evals / "triggering.jsonl").write_text('{"query": "x", "expect": true}\n', encoding="utf-8")
    (func / "tasks.json").write_text('{"tasks": [{"id": "t1"}]}', encoding="utf-8")
    (func / "run_grader.py").write_text("# deterministic grader\n", encoding="utf-8")
    before = content_hash(tmp_path)

    # A harness run writes the output file; the hash must not move.
    (evals / "evals.json").write_text(
        '{"skill_name": "demo", "results": {"date": "2026-06-20"}}', encoding="utf-8"
    )
    assert content_hash(tmp_path) == before
    # A *re-run* rewrites it with a fresh date + a populated results block; still invariant.
    (evals / "evals.json").write_text(
        '{"skill_name": "demo", "results": {"date": "2026-06-21", '
        '"functional": {"eval_pass_rate": 1.0}}}',
        encoding="utf-8",
    )
    assert content_hash(tmp_path) == before
    # And restoring the pre-run state (no results block) is invariant too.
    (evals / "evals.json").write_text('{"skill_name": "demo"}', encoding="utf-8")
    assert content_hash(tmp_path) == before

    # Negative control: editing an authored eval-set file DOES move the hash, so
    # the test contract stays hashed (the parallel to the sidecar-edit test).
    (func / "tasks.json").write_text('{"tasks": [{"id": "t1"}, {"id": "t2"}]}', encoding="utf-8")
    assert content_hash(tmp_path) != before
