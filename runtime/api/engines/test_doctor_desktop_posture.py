"""Desktop readiness uses current native evidence and keeps the full-access gate."""

from types import SimpleNamespace

import pytest

from yoke_core.engines import doctor_session as checks
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def run(monkeypatch, facts, reason=""):
    monkeypatch.setattr(checks, "build_actor", lambda: SimpleNamespace(session_id="current"))
    monkeypatch.setattr(checks, "session_harness", lambda: ("codex", "codex-desktop"))
    observed = []

    def read(session_id):
        observed.append(session_id)
        return facts, reason

    monkeypatch.setattr(checks, "read_codex_session_posture", read)
    monkeypatch.setattr(
        checks, "inspect_unattended_posture",
        lambda *a, **kw: pytest.fail("Desktop must never borrow saved CLI settings"),
    )
    rec = RecordCollector()
    checks.hc_session_harness_unattended_posture(None, DoctorArgs(project="42"), rec)
    assert observed == ["current"]
    return rec.results[0]


def test_full_access_native_turn_passes(monkeypatch):
    result = run(monkeypatch, {
        "approval_policy": "never", "sandbox_mode": "danger-full-access",
    })
    assert result.result == "PASS"
    assert "this turn records" in result.detail


@pytest.mark.parametrize("facts", [
    {"approval_policy": "on-request", "approvals_reviewer": "auto_review",
     "sandbox_mode": "workspace-write"},
    {"approval_policy": "never", "sandbox_mode": "workspace-write"},
    {"approval_policy": "on-request", "sandbox_mode": "danger-full-access"},
    {"approval_policy": None, "sandbox_mode": None},
])
def test_restricted_or_missing_values_cannot_pass(monkeypatch, facts):
    result = run(monkeypatch, facts)
    assert result.result == "FAIL"
    assert "HARNESS_POSTURE_RESTRICTED" in result.detail
    assert "Full Access" in result.detail
    assert "harness-setup --fix" not in result.detail


def test_missing_evidence_names_recovery_without_cli_settings(monkeypatch):
    result = run(monkeypatch, None, "native session transcript is missing")
    assert result.result == "FAIL"
    assert "HARNESS_POSTURE_UNVERIFIED" in result.detail
    assert "native session transcript is missing" in result.detail
    assert "new Desktop chat" in result.detail
    assert "harness-setup --fix" not in result.detail
