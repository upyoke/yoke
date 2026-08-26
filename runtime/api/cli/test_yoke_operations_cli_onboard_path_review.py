"""Review and Apply coverage for installer-owned PATH repair."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.config import onboard_apply_path
from yoke_cli.config import onboard_path_plan
from yoke_cli.config import onboard_wizard_plan_review
from yoke_cli.config import path_doctor


def _plan(tmp_path: Path) -> dict:
    tool_dir = tmp_path / ".local" / "bin"
    harness_dir = tmp_path / "vendor" / "bin"
    return {
        "shell": "zsh",
        "tool_bin_dir": str(tool_dir),
        "login_file": str(tmp_path / ".zprofile"),
        "ssh_file": str(tmp_path / ".zshenv"),
        "directories": [str(tool_dir), str(harness_dir)],
        "directory_tools": {
            str(tool_dir): ["yoke", "uv"],
            str(harness_dir): ["codex"],
        },
        "harness_clis": [
            {
                "harness_id": "claude-code",
                "surface_id": "claude-cli",
                "executable": "claude",
                "path": None,
            },
            {
                "harness_id": "codex",
                "surface_id": "codex-cli",
                "executable": "codex",
                "path": str(harness_dir / "codex"),
            },
        ],
        "unresolved_harness_clis": ["claude", "cursor-agent"],
        "targets": [
            {"surface": "login", "path": str(tmp_path / ".zprofile")},
            {"surface": "ssh", "path": str(tmp_path / ".zshenv")},
        ],
    }


def _resolved(plan: dict) -> list[path_doctor.ToolResolution]:
    tool_dir, harness_dir = plan["directories"]
    return [
        path_doctor.ToolResolution("uv", f"{tool_dir}/uv"),
        path_doctor.ToolResolution("uvx", None),
        path_doctor.ToolResolution("yoke", f"{tool_dir}/yoke"),
        path_doctor.ToolResolution("claude", None),
        path_doctor.ToolResolution("codex", f"{harness_dir}/codex"),
        path_doctor.ToolResolution("cursor-agent", None),
    ]


def test_review_names_exact_files_directories_clis_and_ssh_reason(tmp_path) -> None:
    plan = _plan(tmp_path)
    report = {"plan": {"steps": onboard_path_plan.steps(plan)}}

    grouped = onboard_wizard_plan_review.classify_plan(report)

    assert len(grouped["machine"]) == 2
    login, ssh = grouped["machine"]
    assert str(tmp_path / ".zprofile") in login
    assert str(tmp_path / ".zshenv") in ssh
    for expected in (
        *plan["directories"],
        "yoke",
        "uv",
        "claude",
        "codex",
        "cursor-agent",
    ):
        assert expected in login
        assert expected in ssh
    assert "non-login/SSH" in ssh
    assert f"never reads {tmp_path / '.zprofile'}" in ssh


def test_apply_writes_both_surfaces_and_reports_them_independently(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        path_doctor,
        "verify_fresh_login",
        lambda *_args, **_kwargs: _resolved(plan),
    )
    monkeypatch.setattr(
        path_doctor,
        "verify_ssh_command",
        lambda *_args, **_kwargs: _resolved(plan),
    )
    report: dict = {}

    onboard_apply_path.apply(plan, progress=None, report=report)

    for target in plan["targets"]:
        text = Path(target["path"]).read_text(encoding="utf-8")
        assert path_doctor.MANAGED_BEGIN in text
        assert all(directory in text for directory in plan["directories"])
    assert report["path_repair"]["login_verified"] is True
    assert report["path_repair"]["ssh_verified"] is True
    assert report["path_repair"]["changed_files"] == [
        str(tmp_path / ".zprofile"),
        str(tmp_path / ".zshenv"),
    ]

    rerun: dict = {}
    onboard_apply_path.apply(plan, progress=None, report=rerun)
    assert rerun["path_repair"]["changed_files"] == []


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
