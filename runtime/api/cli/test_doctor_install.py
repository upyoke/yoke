"""The install selection and final setup report preserve complete evidence."""

import pytest

from yoke_cli.commands.adapters import doctor, doctor_install, onboard_apply
from yoke_cli.config.onboard_report_render import render_human


def test_install_expands_existing_only_selection(monkeypatch):
    captured = {}
    monkeypatch.setattr(doctor, "required_project_context", lambda p: "42")
    monkeypatch.setattr(doctor, "_active_transport_is_https", lambda: False)
    monkeypatch.setattr(doctor, "_runtime_for_active_connection", lambda: "local")

    def dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(doctor, "_dispatch_in_process", dispatch)
    assert doctor.doctor_run(["--install"]) == 0
    assert captured["payload"]["only"] == ",".join(doctor_install.install_slugs())
    assert not captured["payload"]["quick"]


def test_install_cannot_be_combined_with_other_scope():
    assert doctor.doctor_run(["--install", "--quick"]) == 2


def test_setup_keeps_failed_readiness_as_a_shown_result(monkeypatch):
    def doctor_run(args):
        print(
            '{"success":true,"result":{"fail_count":1,"results":[{"hc":"hook-resident","severity":"FAIL","detail":"Start a new session."}]}}'
        )
        return 1

    monkeypatch.setattr(doctor, "doctor_run", doctor_run)
    result = doctor_install.setup_readiness({}, {"project_slug": "sample"})
    assert not result["ready"]
    report = {
        "mode": "hosted",
        "config_path": "config",
        "applied": True,
        "plan": {"steps": []},
        "identity": {},
        "next_steps": [],
        "install_health": result,
    }
    rendered = render_human(report)
    assert "Install readiness: needs attention" in rendered
    assert "FAIL: hook-resident" in rendered
    assert "Start a new session" in rendered


def test_readiness_transport_refusal_cannot_be_reported_ready(monkeypatch):
    monkeypatch.setattr(doctor, "doctor_run", lambda a: 2)
    assert not doctor_install.setup_readiness({}, {"project_slug": "sample"})["ready"]


def test_agent_apply_persists_readiness_before_finishing(monkeypatch):
    class Writer:
        payload = {}

        def has_step(self, action):
            return False

        def finish(self, final_status="done"):
            assert self.payload["install_health"] == {"ready": False}

        def summary(self):
            return {"final_status": "done"}

    writer = Writer()
    monkeypatch.setattr(
        onboard_apply.onboard_apply_report.ApplyReportWriter, "start", lambda *a: writer
    )
    monkeypatch.setattr(onboard_apply.onboard_config, "build_report", lambda **k: {})
    monkeypatch.setattr(doctor_install, "setup_readiness", lambda *a: {"ready": False})
    report = onboard_apply._run_locked_apply({}, {}, {})
    assert report["install_health"] == writer.payload["install_health"]


@pytest.mark.parametrize(
    "response",
    [
        '{"success":true,"result":{}}',
        '{"success":true,"result":{"results":[],"fail_count":0}}',
    ],
)
def test_empty_evidence_cannot_be_ready(monkeypatch, response):
    def doctor_run(args):
        print(response)
        return 0

    monkeypatch.setattr(doctor, "doctor_run", doctor_run)
    assert not doctor_install.setup_readiness({}, {"project_slug": "sample"})["ready"]


def test_complete_pass_evidence_is_ready(monkeypatch):
    import json

    def doctor_run(args):
        print(
            json.dumps(
                {
                    "success": True,
                    "result": {
                        "results": [
                            {"hc": "HC-" + slug, "severity": "PASS"}
                            for slug in doctor_install.install_slugs()
                        ]
                    },
                }
            )
        )
        return 0

    monkeypatch.setattr(doctor, "doctor_run", doctor_run)
    assert doctor_install.setup_readiness({}, {"project_slug": "sample"})["ready"]


def test_readiness_crash_keeps_named_recovery(monkeypatch):
    def refuse(args):
        raise OSError("provider unavailable")

    monkeypatch.setattr(doctor, "doctor_run", refuse)
    result = doctor_install.setup_readiness({}, {"project_slug": "sample"})
    assert not result["ready"]
    assert result["error"]["code"] == "INSTALL_DOCTOR_UNAVAILABLE"
    assert result["error"]["cause"] == "OSError"


def test_local_dashboard_publishes_its_packaged_release_header(monkeypatch):
    from fastapi.testclient import TestClient
    from yoke_core.ui.server import create_ui_app
    from yoke_contracts.engine_version import ENGINE_VERSION_HEADER

    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version",
        lambda: "0.1.1+launch.400",
    )
    response = TestClient(create_ui_app("private-test-token")).get("/served-build")
    assert response.status_code == 200
    assert response.headers[ENGINE_VERSION_HEADER] == "0.1.1+launch.400"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "severity,detail,expected",
    [
        ("N/A", "GitHub sync is intentionally disabled", "N/A"),
        ("N/A", "applies only to external projects", "FAIL"),
        ("PASS", "project auth resolved", "PASS"),
        ("FAIL", "token issuance failed", "FAIL"),
    ],
)
def test_install_github_auth_never_treats_an_old_applicability_skip_as_pass(
    severity, detail, expected
):
    result = {
        "results": [
            {"hc": "HC-project-gh-auth", "severity": severity, "detail": detail}
        ]
    }
    doctor_install.normalize_install_result(
        {"only": ",".join(doctor_install.install_slugs())}, result
    )
    assert result["results"][0]["severity"] == expected
    if severity == "N/A" and expected == "FAIL":
        assert "Required serving feature" in result["results"][0]["detail"]
        assert result["fail_count"] == 1


@pytest.mark.parametrize(
    "warning_slug,ready", [("harness-cli-auth", True), ("hook-resident", False)]
)
def test_only_cli_auth_warning_allows_setup_readiness(monkeypatch, warning_slug, ready):
    import json

    def doctor_run(args):
        print(
            json.dumps(
                {
                    "success": True,
                    "result": {
                        "results": [
                            {
                                "hc": "HC-" + slug,
                                "severity": "WARN" if slug == warning_slug else "PASS",
                            }
                            for slug in doctor_install.install_slugs()
                        ]
                    },
                }
            )
        )
        return 0

    monkeypatch.setattr(doctor, "doctor_run", doctor_run)
    assert (
        doctor_install.setup_readiness({}, {"project_slug": "sample"})["ready"] is ready
    )
