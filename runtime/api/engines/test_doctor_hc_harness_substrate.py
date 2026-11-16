"""Tests for HC-harness-substrate-drift."""

from __future__ import annotations

from yoke_project_checks.check_harness_substrate import (
    hc_harness_substrate_drift,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _run_hc() -> RecordCollector:
    rec = RecordCollector()
    hc_harness_substrate_drift(None, DoctorArgs(), rec)
    return rec


def test_pass_when_no_drift(monkeypatch):
    from yoke_core.domain import agents_render

    monkeypatch.setattr(agents_render, "detect_substrate_drift", lambda **_kw: [])
    rec = _run_hc()
    assert rec.results[0].result == "PASS"
    assert "match canonical" in rec.results[0].detail


def test_fail_names_missing_native_views_and_the_fix(monkeypatch):
    from yoke_core.domain import agents_render

    monkeypatch.setattr(
        agents_render,
        "detect_substrate_drift",
        lambda **_kw: [
            "drift: runtime/harness/claude/agents/yoke-engineer.md",
            "missing: .codex/hooks.json",
            "missing: .claude/agents",
        ],
    )
    rec = _run_hc()
    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "yoke-engineer.md" in detail
    assert "missing: .codex/hooks.json" in detail
    assert "missing: .claude/agents" in detail
    assert "Run `yoke agents render` to repair." in detail


def test_fail_when_drift_check_raises(monkeypatch):
    from yoke_core.domain import agents_render

    def boom(**_kw):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(agents_render, "detect_substrate_drift", boom)
    rec = _run_hc()
    assert rec.results[0].result == "FAIL"
    assert "renderer exploded" in rec.results[0].detail
    assert "yoke agents render" in rec.results[0].detail
