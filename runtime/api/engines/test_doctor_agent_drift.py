"""Tests for HC-agent-canonical-drift health check."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


REPO_ROOT = Path(__file__).resolve().parents[3]


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
    from yoke_project_checks.check_agents import hc_agent_canonical_drift

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
    from yoke_project_checks.check_agents import hc_agent_canonical_drift

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
    from yoke_project_checks.check_agents import hc_agent_canonical_drift

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
# test_registered_as_project_check
# ---------------------------------------------------------------------------

def _registered_agent_canonical_drift_checks():
    """Rows for the drift check among this repo's own discovered checks."""
    from yoke_core.engines.doctor_project_checks import discover_project_checks

    checks = discover_project_checks(REPO_ROOT).checks
    return [hc for hc in checks if hc.slug == "agent-canonical-drift"]


def test_registered_as_project_check():
    from yoke_project_checks.check_agents import hc_agent_canonical_drift

    entries = _registered_agent_canonical_drift_checks()
    assert entries, f"agent-canonical-drift not registered under {REPO_ROOT}"
    assert len(entries) == 1
    registered = entries[0].fn
    # Discovery imports a fresh module object per run, so compare the
    # function's identity by module + name rather than by object identity.
    assert (registered.__module__, registered.__name__) == (
        hc_agent_canonical_drift.__module__,
        hc_agent_canonical_drift.__name__,
    )
    assert entries[0].name == "Claude adapter canonical drift"


# ---------------------------------------------------------------------------
# test_slug_vs_record_id_convention
# ---------------------------------------------------------------------------

def test_slug_vs_record_id_convention():
    """The HealthCheck slug has no HC- prefix; rec.record() uses HC- prefix."""
    import inspect
    from yoke_project_checks.check_agents import hc_agent_canonical_drift

    # Slug has no HC- prefix
    slugs = [hc.slug for hc in _registered_agent_canonical_drift_checks()]
    assert len(slugs) == 1
    assert not slugs[0].startswith("HC-")

    # Function body uses HC- prefix in rec.record calls
    source = inspect.getsource(hc_agent_canonical_drift)
    assert '"HC-agent-canonical-drift"' in source
