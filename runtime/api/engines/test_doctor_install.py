"""Install readiness distinguishes observed facts from configuration."""

from types import SimpleNamespace
import subprocess

import pytest

from yoke_core.engines import doctor_install as checks
from yoke_core.engines import doctor_install_guidance as guidance
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_applicability_declarations import local_runtime_slugs
from yoke_core.engines.doctor_https_local_scope import requested_local_machine_slugs


def run(fn, project="42"):
    rec = RecordCollector()
    fn(None, DoctorArgs(project=project), rec)
    assert rec.results
    return rec.results


def test_install_roster_stays_machine_local_without_relaying_new_check_names(
    monkeypatch,
):
    monkeypatch.setattr(
        "yoke_core.engines.doctor_https_local_scope.checkout_root_for_project",
        lambda p: None,
    )
    selected, source = requested_local_machine_slugs(
        {"only": ",".join(checks.INSTALL_SLUGS), "project": "42"}
    )
    assert set(selected) == set(checks.INSTALL_SLUGS) - {"project-gh-auth"}
    assert not source
    assert set(checks.INSTALL_SLUGS) - {"project-gh-auth"} <= local_runtime_slugs()


@pytest.mark.parametrize(
    "payload,code,expected",
    [
        ('{"loggedIn":true,"email":"private@example.invalid"}', 0, "PASS"),
        ('{"loggedIn":false,"token":"private-token"}', 0, "FAIL"),
        ("not-json private-token", 0, "FAIL"),
        ('{"loggedIn":true}', 124, "FAIL"),
    ],
)
def test_native_auth_is_verified_without_printing_private_document(
    monkeypatch, payload, code, expected
):
    monkeypatch.setattr(
        checks,
        "resolve_harness_clis",
        lambda path: [SimpleNamespace(harness_id="claude-code", path="claude")],
    )
    monkeypatch.setattr(
        checks,
        "_run",
        lambda *a, **k: subprocess.CompletedProcess([], code, payload, "private-token"),
    )
    result = run(checks.hc_harness_cli_auth)[0]
    assert result.result == expected
    assert "private" not in result.detail
    if expected == "FAIL":
        assert "claude auth login" in result.detail


def test_absent_harness_is_failed_evidence(monkeypatch):
    monkeypatch.setattr(checks, "resolve_harness_clis", lambda path: [])
    assert run(checks.hc_harness_cli_auth)[0].result == "FAIL"


@pytest.mark.parametrize(
    "expected,served,version,installed,verdict",
    [
        ("a" * 40, "a" * 40, "", "", "PASS"),
        ("a" * 40, "b" * 40, "", "", "FAIL"),
        ("a" * 40, "a" * 40 + "-dirty", "", "", "FAIL"),
        ("unknown", "", "0.1.1+launch.400", "0.1.1+launch.400", "PASS"),
        ("unknown", "", "", "0.1.1+launch.400", "FAIL"),
        ("unknown", "", "0.1.0", "0.1.0", "FAIL"),
    ],
)
def test_dashboard_requires_matching_source_or_packaged_identity(
    monkeypatch, expected, served, version, installed, verdict
):
    monkeypatch.setattr(checks, "dashboard_identity", lambda: (served, version))
    monkeypatch.setattr(
        checks, "collect_execution_provenance", lambda: {"source_sha": expected}
    )
    monkeypatch.setattr(checks, "local_handshake_version", lambda: installed)
    result = run(checks.hc_dashboard_current_build)[0]
    assert result.result == verdict
    if verdict == "FAIL":
        assert "yoke ui down" in result.detail


def test_stopped_dashboard_fails_with_restart(monkeypatch):
    def stopped():
        raise ValueError("DASHBOARD_NOT_RUNNING")

    monkeypatch.setattr(checks, "dashboard_identity", stopped)
    assert run(checks.hc_dashboard_current_build)[0].result == "FAIL"


@pytest.mark.parametrize(
    "session,registered,delivered,verdict",
    [
        ("session", "session", True, "PASS"),
        ("session", "session", False, "FAIL"),
        ("session", "other", True, "FAIL"),
        ("", "", True, "FAIL"),
    ],
)
def test_hook_requires_both_registered_identity_and_observed_delivery(
    monkeypatch, session, registered, delivered, verdict
):
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id=session)
    )
    monkeypatch.setattr(
        checks, "relay", lambda *a: {"session_id": registered, "project_id": 42}
    )
    monkeypatch.setattr(checks, "orientation_delivered", lambda s: delivered)
    assert run(checks.hc_session_hook_registration)[0].result == verdict


@pytest.mark.parametrize(
    "relationship,verdict",
    [("running_equal", "PASS"), ("running_unknown", "FAIL"), ("running_ahead", "FAIL")],
)
def test_guidance_receipt_is_not_certified_when_unknown_or_different(
    monkeypatch, tmp_path, relationship, verdict
):
    monkeypatch.setattr(guidance, "project_root", lambda a: tmp_path)
    monkeypatch.setattr(
        guidance.project_installed_layer,
        "scan",
        lambda r: SimpleNamespace(present=True),
    )
    monkeypatch.setattr(
        guidance.operating_layer_drift,
        "running_identity",
        lambda: ("release", "origin"),
    )
    monkeypatch.setattr(
        guidance.operating_layer_drift,
        "compare_installed_layer",
        lambda *a, **k: SimpleNamespace(
            running=SimpleNamespace(relationship=relationship)
        ),
    )
    assert run(guidance.hc_installed_guidance)[0].result == verdict


def test_missing_instruction_pointer_fails_even_with_configured_hooks(
    monkeypatch, tmp_path
):
    (tmp_path / "AGENTS.md").write_text("configured")
    monkeypatch.setattr(guidance, "project_root", lambda a: tmp_path)
    assert run(guidance.hc_instruction_discovery)[0].result == "FAIL"


@pytest.mark.parametrize(
    "config",
    [
        {
            "active_env": "local",
            "connection_projects": {
                "local": [{"checkout": "/tmp/install-test", "project_id": 42}]
            },
        },
        {"projects": {"/tmp/install-test": {"project_id": 42}}},
    ],
)
def test_residue_detects_foreign_project_binding_for_supported_mapping_shapes(
    monkeypatch, config
):
    from pathlib import Path

    monkeypatch.setattr(guidance, "project_root", lambda a: Path("/tmp/install-test"))
    monkeypatch.setattr(guidance, "hook_config_yoke_problems", lambda *a: [])
    monkeypatch.setattr(guidance, "enumerate_shadow_installs", lambda **k: [])
    monkeypatch.setattr(guidance, "load_manifest", lambda r: {"project_id": 99})
    monkeypatch.setattr(guidance.machine_config, "load_config", lambda: config)
    result = run(guidance.hc_install_residue)[0]
    assert result.result == "FAIL"
    assert (
        "another project's binding"
        if isinstance(config["projects"], list)
        else "projects_invalid"
    ) in result.detail


def test_hook_delivery_from_another_project_cannot_prove_install_readiness(monkeypatch):
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )
    monkeypatch.setattr(
        checks, "relay", lambda *a: {"session_id": "session", "project_id": 99}
    )
    monkeypatch.setattr(checks, "orientation_delivered", lambda session: True)
    result = run(checks.hc_session_hook_registration, project="42")[0]
    assert result.result == "FAIL"
    assert "Start a new harness session" in result.detail
