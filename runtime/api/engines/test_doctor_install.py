"""Install readiness distinguishes observed facts from configuration."""

from types import SimpleNamespace
import subprocess

import pytest

from yoke_core.engines import doctor_install as checks
from yoke_core.engines import doctor_install_guidance as guidance
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_applicability_declarations import local_runtime_slugs
from yoke_core.engines.doctor_https_local_scope import requested_local_machine_slugs


def answers(refusal="not_found", **identity):
    def relay(function, payload):
        if function != "projects.get":
            return identity
        if payload["project"] not in {"42", "yoke"}:
            raise checks.ControlPlaneRefused("projects.get refused", code=refusal)
        return {"value": 42}

    return relay


def run(fn, project="42", **kwargs):
    rec = RecordCollector()
    fn(None, DoctorArgs(project=project, **kwargs), rec)
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
        ('{"loggedIn":false,"token":"private-token"}', 0, "WARN"),
        ("not-json private-token", 0, "WARN"),
        ('{"loggedIn":true}', 124, "WARN"),
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
    if expected == "WARN":
        assert "claude auth login" in result.detail


def test_absent_harness_is_warning_evidence(monkeypatch):
    monkeypatch.setattr(checks, "resolve_harness_clis", lambda path: [])
    assert run(checks.hc_harness_cli_auth)[0].result == "WARN"


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
    monkeypatch.setattr(checks, "active_https_connection", lambda: None)
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

    monkeypatch.setattr(checks, "active_https_connection", lambda: None)
    monkeypatch.setattr(checks, "dashboard_identity", stopped)
    assert run(checks.hc_dashboard_current_build)[0].result == "FAIL"


def test_https_connection_dashboard_is_not_applicable_without_ui_advice(monkeypatch):
    monkeypatch.setattr(
        checks.machine_config,
        "active_connection",
        lambda: {
            "env": "prod",
            "transport": "https",
            "api_url": "https://acme.upyoke.com/api",
        },
    )

    def unreachable():
        raise AssertionError("an https connection has no local dashboard to probe")

    monkeypatch.setattr(checks, "dashboard_identity", unreachable)
    result = run(checks.hc_dashboard_current_build)[0]
    assert result.result == "N/A"
    assert "https://acme.upyoke.com/" in result.detail
    assert "yoke ui" not in result.detail


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
    monkeypatch.setattr(checks, "relay", answers(session_id=registered, project_id=42))
    monkeypatch.setattr(checks, "orientation_delivered", lambda s: delivered)
    assert (
        run(checks.hc_session_hook_registration, only="session-hook-registration")[
            0
        ].result
        == verdict
    )


@pytest.mark.parametrize("session", ["", "session"])
@pytest.mark.parametrize("selection", ["install", "session", "named", "ordinary"])
def test_install_skips_only_absent_session_and_session_scope_still_requires_proof(
    monkeypatch, session, selection
):
    from yoke_core.engines.doctor_session import SESSION_SLUGS

    only = {
        "install": ",".join(checks.INSTALL_SLUGS),
        "session": ",".join(SESSION_SLUGS),
        "named": "session-hook-registration",
        "ordinary": None,
    }[selection]
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id=session)
    )
    calls = []

    def identity(*args):
        calls.append(args)
        return answers(session_id=session, project_id=42)(*args)

    monkeypatch.setattr(checks, "relay", identity)
    monkeypatch.setattr(checks, "orientation_delivered", lambda s: False)
    result = run(checks.hc_session_hook_registration, only=only)[0]
    skipped = not session and selection in {"install", "ordinary"}
    assert result.result == ("N/A" if skipped else "FAIL")
    assert bool(calls) == bool(session)
    if skipped:
        assert "session_required" in result.detail
        assert "yoke doctor run --session" in result.detail


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
        {
            "active_env": "local",
            "connection_projects": {"local": {"/tmp/install-test": {"project_id": 42}}},
        },
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
        if isinstance(config["connection_projects"]["local"], list)
        else "projects_invalid"
    ) in result.detail


def test_hook_delivery_from_another_project_cannot_prove_install_readiness(monkeypatch):
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )
    monkeypatch.setattr(checks, "relay", answers(session_id="session", project_id=99))
    monkeypatch.setattr(checks, "orientation_delivered", lambda session: True)
    result = run(checks.hc_session_hook_registration, project="42")[0]
    assert result.result == "FAIL"
    assert "SESSION_HOOK_PROJECT_MISMATCH" in result.detail


@pytest.mark.parametrize("refusal", ["not_found", "permission_denied", ""])
@pytest.mark.parametrize("project", ["missing-slug", "99999"])
def test_only_a_not_found_project_read_fails_as_project_not_found(
    monkeypatch, project, refusal
):
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )
    identity = answers(refusal, session_id="session", project_id=42)
    monkeypatch.setattr(checks, "relay", identity)
    monkeypatch.setattr(checks, "orientation_delivered", lambda session: True)
    result = run(checks.hc_session_hook_registration, project=project)[0]
    assert result.result == "FAIL"
    assert result.detail.startswith("project_not_found") == (refusal == "not_found")
    assert ("SESSION_HOOK_CHECK_FAILED" in result.detail) == (refusal != "not_found")


@pytest.mark.parametrize("project_id", [None, 42])
@pytest.mark.parametrize("delivered", [False, True])
def test_hook_readiness_reads_delivery_in_the_registered_scope(
    monkeypatch, tmp_path, project_id, delivered
):
    from contextlib import nullcontext
    from yoke_core.domain import project_scratch_identity
    from yoke_core.domain.project_scratch_dir import hook_marker_path, scratch_project

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(
        project_scratch_identity, "machine_scope_namespace", lambda: ("_machine-test",)
    )
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )
    identity = answers(session_id="session", project_id=project_id)
    monkeypatch.setattr(checks, "relay", identity)
    # The marker in the other scope must never stand in for this session's proof.
    for scope in (None, 42):
        with scratch_project(str(scope)) if scope else nullcontext():
            if scope != project_id or delivered:
                hook_marker_path("session-orientation-delivered-session").touch()
    result = run(checks.hc_session_hook_registration, project=None)[0]
    assert result.result == ("PASS" if delivered else "FAIL")


@pytest.mark.parametrize(
    "error", [RuntimeError("authority_unreachable"), OSError("marker_unreadable")]
)
def test_hook_observation_failures_preserve_their_actual_reason(monkeypatch, error):
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )

    def refused(*args):
        raise error

    monkeypatch.setattr(checks, "relay", refused)
    result = run(checks.hc_session_hook_registration)[0]
    assert result.result == "FAIL"
    assert str(error) in result.detail
    assert "SESSION_HOOK_UNOBSERVED" not in result.detail


def test_unexpected_hook_check_errors_are_not_mislabeled_as_missing_delivery(
    monkeypatch,
):
    monkeypatch.setattr(
        checks, "build_actor", lambda: SimpleNamespace(session_id="session")
    )
    monkeypatch.setattr(checks, "relay", lambda *a: None)
    with pytest.raises(AttributeError):
        run(checks.hc_session_hook_registration)
