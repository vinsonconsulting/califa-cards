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
    (tmp_path / "card-review.md").write_text("# review\n", encoding="utf-8")
    # The authored governance sidecar is excluded: status/finding decisions are
    # overlay data, not the code the hash describes.
    (tmp_path / "card.authored.yaml").write_text("status: beta\n", encoding="utf-8")

    assert content_hash(tmp_path) == before
