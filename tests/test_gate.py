"""Gate tests: each score band and the CRITICAL-severity override."""

from __future__ import annotations

from skillcard.gate import GateResult, evaluate, extract_findings, extract_score


def _report(score, findings=None):
    return {"risk_assessment": {"score": score}, "issues": findings or []}


def _card(findings):
    return {"scan": {"findings": findings}}


def test_low_band_passes_without_card():
    r = evaluate(_report(12, [{"rule_id": "AST4", "severity": "MEDIUM"}]))
    assert isinstance(r, GateResult)
    assert r.passed
    assert r.band == "LOW"


def test_medium_band_fails_without_card():
    r = evaluate(_report(30, [{"rule_id": "AST4", "severity": "MEDIUM"}]))
    assert not r.passed
    assert r.band == "MEDIUM"


def test_medium_band_passes_when_accepted_and_noted():
    card = _card([{"rule_id": "AST4", "status": "accepted", "note": "shells out to pytest"}])
    r = evaluate(_report(30, [{"rule_id": "AST4", "severity": "MEDIUM"}]), card)
    assert r.passed


def test_medium_band_fails_when_not_accepted():
    card = _card([{"rule_id": "AST4", "status": "resolved", "note": "x"}])
    r = evaluate(_report(30, [{"rule_id": "AST4", "severity": "MEDIUM"}]), card)
    assert not r.passed


def test_medium_band_fails_when_note_blank():
    card = _card([{"rule_id": "AST4", "status": "accepted", "note": "  "}])
    r = evaluate(_report(30, [{"rule_id": "AST4", "severity": "MEDIUM"}]), card)
    assert not r.passed


def test_medium_band_fails_when_finding_absent_from_card():
    card = _card([{"rule_id": "AST7", "status": "accepted", "note": "other"}])
    r = evaluate(_report(30, [{"rule_id": "AST4", "severity": "MEDIUM"}]), card)
    assert not r.passed


def test_high_band_hard_fails():
    r = evaluate(_report(60, [{"rule_id": "X", "severity": "HIGH"}]))
    assert not r.passed
    assert r.band == "HIGH"


def test_critical_band_hard_fails():
    r = evaluate(_report(90))
    assert not r.passed
    assert r.band == "CRITICAL"


def test_critical_severity_finding_overrides_low_score():
    # A CRITICAL finding hard-fails even when the total score sits in LOW.
    r = evaluate(_report(10, [{"rule_id": "AST1", "severity": "CRITICAL"}]))
    assert not r.passed
    assert "CRITICAL" in r.reasons[0]


def test_score_extraction_fallback_keys():
    assert extract_score({"risk_score": 15}) == 15
    assert extract_score({"score": 7}) == 7
    assert extract_score({"risk_assessment": {"score": 22}}) == 22


def test_findings_extraction_fallback_keys():
    assert extract_findings({"findings": [{"severity": "LOW"}]}) == [{"severity": "LOW"}]
    assert extract_findings({"filtered_findings": [{"severity": "LOW"}]}) == [{"severity": "LOW"}]
    assert extract_findings({}) == []
