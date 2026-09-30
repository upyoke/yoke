"""Review and Apply coverage for installer-owned PATH repair."""

from __future__ import annotations


from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.config import onboard_apply_path
from yoke_cli.config import onboard_path_plan
from yoke_cli.config import onboard_wizard_plan_review
from yoke_cli.config import path_doctor


def _plan() -> dict:
    return {
        "shell": "zsh",
        "targets": [{"surface": "shell", "path": "uv tool update-shell"}],
    }


def test_review_names_uv_shell_setup():
    grouped = onboard_wizard_plan_review.classify_plan(
        {"plan": {"steps": onboard_path_plan.steps(_plan())}}
    )
    assert len(grouped["machine"]) == 1
    assert "uv tool update-shell" in grouped["machine"][0]


def test_apply_delegates_and_reports_real_login(monkeypatch):
    calls = []
    monkeypatch.setattr(
        path_doctor,
        "update_shell",
        lambda: calls.append("uv tool update-shell") or "updated",
    )
    monkeypatch.setattr(
        path_doctor,
        "verify_fresh_login",
        lambda *_args: [path_doctor.ToolResolution("yoke", "/tmp/bin/yoke")],
    )
    report = {}
    onboard_apply_path.apply(_plan(), progress=None, report=report)
    assert calls == ["uv tool update-shell"]
    assert report["path_repair"]["login_verified"] is True


def test_noninteractive_onboard_injects_the_detected_path_plan(monkeypatch) -> None:
    diagnosis = object()
    expected = {"targets": [], "directories": ["/home/u/.local/bin"]}
    observed: dict = {}
    monkeypatch.setattr(onboard_apply.path_doctor, "diagnose", lambda: diagnosis)
    monkeypatch.setattr(
        onboard_apply.path_repair_plan,
        "build",
        lambda value: expected if value is diagnosis else None,
    )
    monkeypatch.setattr(
        onboard_apply.onboard_config,
        "build_report",
        lambda **kwargs: observed.update(kwargs) or {"plan": {}},
    )

    onboard_apply.apply_with_durable_report({"apply": False})

    assert observed["path_repair"] == expected
