"""Doctor reports setup facets and durable relay failures and calls shared fix."""

from types import SimpleNamespace

from yoke_core.engines import doctor_hc_harness_setup as doctor
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_harness.harness_setup_reconcile import HarnessSetupResult, HarnessSetupRow


def test_inspect_fix_and_relay_failure(monkeypatch):
    missing = HarnessSetupResult(
        (
            HarnessSetupRow(
                "repo", "codex", "folder_trust", "refused", "missing", "repair"
            ),
        )
    )
    ready = HarnessSetupResult(
        (HarnessSetupRow("repo", "codex", "folder_trust", "already_set"),)
    )
    monkeypatch.setattr(doctor, "inspect_harness_setup", lambda: missing)
    monkeypatch.setattr(doctor, "reconcile_harness_setup", lambda: ready)
    monkeypatch.setattr(doctor, "codex_home_without_codex", lambda: "")
    monkeypatch.setattr(
        doctor, "installed_machine_hooks", lambda: [SimpleNamespace(harness_id="codex")]
    )
    monkeypatch.setattr(doctor, "read_reconcile_state", lambda: {})
    monkeypatch.setattr(doctor, "remember_reconcile_result", lambda result: None)
    rec = RecordCollector()
    doctor.hc_harness_setup(None, DoctorArgs(), rec)
    assert rec.results[-1].result == "FAIL"
    assert "missing" in rec.results[-1].detail and "--fix" in rec.results[-1].detail
    doctor.hc_harness_setup(None, DoctorArgs(fix=True), rec)
    assert rec.results[-1].result == "PASS"
    monkeypatch.setattr(
        doctor, "read_reconcile_state", lambda: {"failure": "previous refusal"}
    )
    doctor.hc_harness_setup(None, DoctorArgs(fix=True), rec)
    assert "previous refusal" in rec.results[-1].detail


def test_no_homes_is_not_applicable(monkeypatch):
    monkeypatch.setattr(doctor, "inspect_harness_setup", lambda: HarnessSetupResult(()))
    monkeypatch.setattr(doctor, "installed_machine_hooks", lambda: [])
    monkeypatch.setattr(doctor, "read_reconcile_state", lambda: {})
    rec = RecordCollector()
    doctor.hc_harness_setup(None, DoctorArgs(), rec)
    assert rec.results[0].result == "N/A"


def test_orphan_codex_home_reports_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(
        doctor,
        "installed_machine_hooks",
        lambda: [SimpleNamespace(harness_id="codex", home_path=lambda: tmp_path)],
    )
    monkeypatch.setattr(doctor, "resolve_native_cli", lambda name: None)
    monkeypatch.setattr(
        doctor, "APP_SURFACE_PROBES", {"codex-desktop": tmp_path / "absent"}
    )
    assert "codex_home_without_codex" in doctor.codex_home_without_codex()
    assert "otherwise open Codex once" in doctor.codex_home_without_codex()
