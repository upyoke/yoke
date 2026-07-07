"""Tests for HC-agent-canonical-drift health check."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_rec() -> MagicMock:
    """Return a mock RecordCollector that captures record() calls."""
    return MagicMock()


def _make_args() -> MagicMock:
    """Return a mock DoctorArgs."""
    return MagicMock()


# ---------------------------------------------------------------------------
# test_no_drift_passes
# ---------------------------------------------------------------------------

def test_no_drift_passes(monkeypatch):
    from yoke_core.engines.doctor import hc_agent_canonical_drift

    monkeypatch.setattr(
        "yoke_core.domain.agents_render.detect_drift", lambda: []
    )
    rec = _make_rec()
    hc_agent_canonical_drift(None, _make_args(), rec)
    rec.record.assert_called_once_with(
        "HC-agent-canonical-drift",
        "Claude adapter canonical drift",
        "PASS",
        "",
    )


# ---------------------------------------------------------------------------
# test_drift_fails
# ---------------------------------------------------------------------------

def test_drift_fails(monkeypatch):
    from yoke_core.engines.doctor import hc_agent_canonical_drift

    monkeypatch.setattr(
        "yoke_core.domain.agents_render.detect_drift",
        lambda: ["yoke-architect.md: bytes differ"],
    )
    rec = _make_rec()
    hc_agent_canonical_drift(None, _make_args(), rec)
    rec.record.assert_called_once_with(
        "HC-agent-canonical-drift",
        "Claude adapter canonical drift",
        "FAIL",
        "- yoke-architect.md: bytes differ",
    )


# ---------------------------------------------------------------------------
# test_detection_exception_fails
# ---------------------------------------------------------------------------

def test_detection_exception_fails(monkeypatch):
    from yoke_core.engines.doctor import hc_agent_canonical_drift

    def _boom():
        raise RuntimeError("no such file")

    monkeypatch.setattr(
        "yoke_core.domain.agents_render.detect_drift", _boom
    )
    rec = _make_rec()
    hc_agent_canonical_drift(None, _make_args(), rec)
    rec.record.assert_called_once()
    call_args = rec.record.call_args[0]
    assert call_args[0] == "HC-agent-canonical-drift"
    assert call_args[2] == "FAIL"
    assert "no such file" in call_args[3]


# ---------------------------------------------------------------------------
# test_run_checks_nonzero_on_drift
# ---------------------------------------------------------------------------

def test_run_checks_nonzero_on_drift(monkeypatch, tmp_path):
    from yoke_core.engines.doctor import DoctorArgs, run_checks

    monkeypatch.setattr(
        "yoke_core.domain.agents_render.detect_drift",
        lambda: ["yoke-architect.md: bytes differ"],
    )
    exit_code = run_checks(
        DoctorArgs(only="agent-canonical-drift", db_path=str(tmp_path / "doctor.db"))
    )
    assert exit_code == 1


# ---------------------------------------------------------------------------
# test_registered_in_health_checks
# ---------------------------------------------------------------------------

def test_registered_in_health_checks():
    from yoke_core.engines.doctor import HEALTH_CHECKS, hc_agent_canonical_drift

    entry = None
    for hc in HEALTH_CHECKS:
        if hc.slug == "agent-canonical-drift":
            entry = hc
            break
    assert entry is not None, "agent-canonical-drift not found in HEALTH_CHECKS"
    assert entry.fn is hc_agent_canonical_drift
    assert entry.name == "Claude adapter canonical drift"


# ---------------------------------------------------------------------------
# test_slug_vs_record_id_convention
# ---------------------------------------------------------------------------

def test_slug_vs_record_id_convention():
    """The HealthCheck slug has no HC- prefix; rec.record() uses HC- prefix."""
    import inspect
    from yoke_core.engines.doctor import HEALTH_CHECKS, hc_agent_canonical_drift

    # Slug has no HC- prefix
    slugs = [hc.slug for hc in HEALTH_CHECKS if hc.slug == "agent-canonical-drift"]
    assert len(slugs) == 1
    assert not slugs[0].startswith("HC-")

    # Function body uses HC- prefix in rec.record calls
    source = inspect.getsource(hc_agent_canonical_drift)
    assert '"HC-agent-canonical-drift"' in source
