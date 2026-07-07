from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_project
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_publish_support import PublishRequest


def _preview() -> dict:
    return {
        "operation": "onboard",
        "mode": "quick",
        "project_mode": "machine-only",
        "config_path": "/tmp/home/config.json",
        "plan": {
            "project": None,
            "steps": [
                {"action": "create-or-validate-dir", "target": "/tmp/home"},
                {"action": "set-active-env", "target": "stage"},
                {"action": "store-token-reference", "target": "/tmp/token"},
            ],
        },
    }


def test_resume_writer_reuses_run_id_and_completed_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    writer = onboard_apply_report.ApplyReportWriter.start(_preview(), {})
    writer.step_started("create-or-validate-dir", "/tmp/home")
    writer.step_done("create-or-validate-dir", "/tmp/home")
    writer.fail(RuntimeError("network down"))
    previous = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))

    resumed = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"resume_run_id": previous["run_id"], "resume_payload": previous},
    )

    payload = json.loads(Path(resumed.summary()["path"]).read_text(encoding="utf-8"))
    assert payload["run_id"] == previous["run_id"]
    statuses = {step["action"]: step["status"] for step in payload["steps"]}
    assert statuses["create-or-validate-dir"] == "done"
    assert statuses["set-active-env"] == "pending"
    assert payload["resume_command"].endswith(previous["run_id"])


def test_cli_resume_loads_snapshot_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    token_file = tmp_path / "token"
    token_file.write_text("resume-token", encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "config_path": str(config),
            "env_name": "stage",
            "api_url": "https://api.stage.example",
            "token_file": str(token_file),
            "token_source_kind": "file",
            "mode": "quick",
            "project_mode": "machine-only",
        },
    )
    run_id = writer.summary()["run_id"]

    rc = onboard_adapter.onboard([
        "--resume", run_id,
        "--yes",
        "--non-interactive",
        "--skip-identity-check",
    ])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Yoke onboard" in out
    assert str(config) in out
    assert config.is_file()
    payload = json.loads(
        onboard_apply_report.run_report_path(run_id).read_text(encoding="utf-8")
    )
    assert payload["final_status"] == "done"
    assert payload["resume_command"] == f"yoke onboard --resume {run_id}"


def test_cli_resume_restores_saved_project_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    yoke_token_file = tmp_path / "yoke.token"
    yoke_token_file.write_text("resume-yoke-token", encoding="utf-8")
    github_token_file = tmp_path / "github.token"
    github_token_file.write_text("resume-github-token", encoding="utf-8")
    publish = PublishRequest(
        owner="octo-org",
        name="widget-copy",
        user_login="octocat",
        token="not-written",
        api_url="https://api.github.example",
        private=False,
    )
    clone = ClonePlan(
        outcome="make-it-mine",
        keep_upstream=True,
        publish=publish,
        fallback_token="not-written",
        fork_api_url="https://api.github.example",
    )
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "config_path": str(config),
            "env_name": "stage",
            "api_url": "https://api.stage.example",
            "token_file": str(yoke_token_file),
            "token_source_kind": "file",
            "mode": "quick",
            "machine_github_choice": "connect",
            "machine_github_api_url": "https://api.github.example",
            "machine_github_token_file": str(github_token_file),
            "machine_github_token_source_kind": "file",
            "project_mode": "clone-remote",
            "project_remote_url": "https://github.com/octo/source.git",
            "project_checkout": str(tmp_path / "widget"),
            "project_slug": "widget",
            "project_name": "Widget",
            "project_github_repo": "octo/source",
            "project_default_branch": "trunk",
            "project_default_branch_source": (
                onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO
            ),
            "project_public_item_prefix": "WID",
            "project_github_adoption": "skip",
            "project_clone": clone,
        },
    )
    run_id = writer.summary()["run_id"]
    captured: list[dict] = []

    def fake_apply_with_durable_report(kwargs, tui_progress=None):
        captured.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        onboard_adapter,
        "_apply_with_durable_report",
        fake_apply_with_durable_report,
    )

    rc = onboard_adapter.onboard([
        "--resume", run_id,
        "--yes",
        "--non-interactive",
        "--json",
        "--skip-identity-check",
    ])

    assert rc == 0
    assert captured
    kwargs = captured[0]
    assert kwargs["machine_github_choice"] == "connect"
    assert kwargs["machine_github_token_file"] == str(github_token_file)
    assert kwargs["machine_github_token"] == "resume-github-token"
    assert kwargs["project_default_branch_source"] == (
        onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO
    )
    saved_clone = kwargs["project_clone"]
    assert isinstance(saved_clone, ClonePlan)
    assert saved_clone.outcome == "make-it-mine"
    assert saved_clone.fallback_token == "resume-github-token"
    assert saved_clone.fork_api_url == "https://api.github.example"
    saved_publish = saved_clone.publish
    assert isinstance(saved_publish, PublishRequest)
    assert saved_publish.owner == "octo-org"
    assert saved_publish.name == "widget-copy"
    assert saved_publish.user_login == "octocat"
    assert saved_publish.token == "resume-github-token"
    assert saved_publish.private is False
    out = capsys.readouterr().out
    assert "resume-github-token" not in out


def test_start_over_requires_yes_before_removing_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "fresh-checkout"
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"project_mode": "clone-remote", "project_checkout": str(checkout)},
    )
    checkout.mkdir()
    run_id = writer.summary()["run_id"]

    rc = onboard_adapter.onboard(["--start-over", run_id])

    assert rc == 2
    assert "--start-over requires --yes" in capsys.readouterr().err
    assert checkout.is_dir()


def test_start_over_removes_run_created_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "fresh-checkout"
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"project_mode": "clone-remote", "project_checkout": str(checkout)},
    )
    checkout.mkdir()
    run_id = writer.summary()["run_id"]

    rc = onboard_adapter.onboard(["--start-over", run_id, "--yes"])

    assert rc == 0
    assert "removed checkout: yes" in capsys.readouterr().out
    assert not checkout.exists()
    payload = json.loads(
        onboard_apply_report.run_report_path(run_id).read_text(encoding="utf-8")
    )
    assert payload["final_status"] == "started-over"
    assert payload["start_over"]["removed_checkout"] is True
    assert payload["start_over"]["remote_repo_removed"] is False


def test_start_over_refuses_existing_local_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "existing"
    checkout.mkdir()
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"project_mode": "local-checkout", "project_checkout": str(checkout)},
    )
    run_id = writer.summary()["run_id"]

    rc = onboard_adapter.onboard(["--start-over", run_id, "--yes"])

    assert rc == 2
    assert "no checkout Yoke can safely remove" in capsys.readouterr().err
    assert checkout.is_dir()
