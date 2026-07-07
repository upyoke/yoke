"""Tests for HC-harness-substrate-drift."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.engines.doctor_hc_harness_substrate import (
    hc_harness_substrate_drift,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _run_hc(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_harness_substrate_drift(conn, DoctorArgs(), rec)
    return rec


def test_pass_when_no_drift(monkeypatch, conn):
    from yoke_core.domain import agents_render

    monkeypatch.setattr(agents_render, "detect_drift", lambda: [])
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"
    assert "match canonical" in rec.results[0].detail


def test_fail_when_renderer_reports_drift(monkeypatch, conn):
    from yoke_core.domain import agents_render

    monkeypatch.setattr(
        agents_render,
        "detect_drift",
        lambda: [
            "drift: runtime/harness/claude/agents/yoke-engineer.md",
            "missing: runtime/harness/claude/agents/yoke-tester.md",
        ],
    )
    rec = _run_hc(conn)
    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "yoke-engineer.md" in detail
    assert "yoke-tester.md" in detail
    assert "agents_render render" in detail


def test_pass_when_renderer_exposes_no_drift_function(monkeypatch, conn):
    """Defensive PASS when the renderer exposes neither name.

    Mirrors the hc_path_integrity precedent for missing substrate.
    """
    from yoke_core.domain import agents_render

    monkeypatch.delattr(agents_render, "detect_drift", raising=False)
    monkeypatch.delattr(agents_render, "check_drift", raising=False)
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"
    assert "not yet provisioned" in rec.results[0].detail


def test_fail_when_drift_check_raises(monkeypatch, conn):
    from yoke_core.domain import agents_render

    def boom():
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(agents_render, "detect_drift", boom)
    rec = _run_hc(conn)
    assert rec.results[0].result == "FAIL"
    assert "renderer exploded" in rec.results[0].detail


def test_falls_back_to_check_drift_when_only_alias_present(monkeypatch, conn):
    """If the canonical name is absent but the legacy alias exists, use it."""
    from yoke_core.domain import agents_render

    monkeypatch.delattr(agents_render, "detect_drift", raising=False)
    monkeypatch.setattr(
        agents_render, "check_drift", lambda: [], raising=False,
    )
    rec = _run_hc(conn)
    assert rec.results[0].result == "PASS"
