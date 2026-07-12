from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_apply_resume
from yoke_cli.config import onboard_checkout_ownership
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


def test_resume_restores_exact_repository_identity_as_integers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "project_mode": "local-checkout",
            "project_checkout": str(tmp_path / "checkout"),
            "project_github_repo": "owner/demo",
            "project_github_adoption": "app-binding",
            "project_github_repository_id": 456,
            "project_github_installation_id": 123,
        },
    )
    snapshot = json.loads(
        Path(writer.summary()["path"]).read_text(encoding="utf-8")
    )["input_snapshot"]
    parsed = SimpleNamespace()

    onboard_apply_resume.apply_defaults(parsed, snapshot)

    assert parsed.project_github_repository_id == 456
    assert isinstance(parsed.project_github_repository_id, int)
    assert parsed.project_github_installation_id == 123
    assert isinstance(parsed.project_github_installation_id, int)


def test_cli_resume_restores_saved_project_choices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    yoke_token_file = tmp_path / "yoke.token"
    yoke_token_file.write_text("resume-yoke-token", encoding="utf-8")
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
            "project_github_adoption": "backlog-only",
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
    monkeypatch.setattr(
        onboard_adapter,
        "_github_user_access_token",
        lambda *_args, **_kwargs: "resume-github-app-user-token",
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
    assert "machine_github_token" not in kwargs
    assert "machine_github_token_file" not in kwargs
    assert "machine_github_token_source_kind" not in kwargs
    assert kwargs["project_default_branch_source"] == (
        onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO
    )
    saved_clone = kwargs["project_clone"]
    assert isinstance(saved_clone, ClonePlan)
    assert saved_clone.outcome == "make-it-mine"
    assert saved_clone.fallback_token == "resume-github-app-user-token"
    assert saved_clone.fork_api_url == "https://api.github.example"
    saved_publish = saved_clone.publish
    assert isinstance(saved_publish, PublishRequest)
    assert saved_publish.owner == "octo-org"
    assert saved_publish.name == "widget-copy"
    assert saved_publish.user_login == "octocat"
    assert saved_publish.token == "resume-github-app-user-token"
    assert saved_publish.private is False
    out = capsys.readouterr().out
    assert "resume-github-app-user-token" not in out


def test_use_different_folder_requires_yes_before_preserving_checkout(
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

    rc = onboard_adapter.onboard(["--use-different-folder", run_id])

    assert rc == 2
    assert "--use-different-folder requires --yes" in capsys.readouterr().err
    assert checkout.is_dir()


def test_use_different_folder_preserves_run_created_checkout(
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
    (checkout / ".git").mkdir(parents=True)
    assert onboard_checkout_ownership.mark_created(checkout)
    writer.write()
    run_id = writer.summary()["run_id"]

    rc = onboard_adapter.onboard([
        "--use-different-folder", run_id, "--yes",
    ])

    assert rc == 0
    assert "preserved checkout:" in capsys.readouterr().out
    assert checkout.exists()
    payload = json.loads(
        onboard_apply_report.run_report_path(run_id).read_text(encoding="utf-8")
    )
    assert payload["final_status"] == "checkout-preserved"
    assert payload["new_target"]["removed_checkout"] is False
    preserved = Path(payload["new_target"]["preserved_checkout_path"])
    assert preserved == checkout
    assert preserved.is_dir()
    assert onboard_checkout_ownership.matches(
        preserved, payload["input_snapshot"]["checkout_provenance"]["ownership"],
    )
    assert payload["new_target"]["remote_repo_removed"] is False


def test_start_over_refuses_replaced_run_created_checkout(
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
    (checkout / ".git").mkdir(parents=True)
    assert onboard_checkout_ownership.mark_created(checkout)
    writer.write()
    run_id = writer.summary()["run_id"]
    original = tmp_path / "original-checkout"
    checkout.rename(original)
    checkout.mkdir()
    (checkout / "keep.txt").write_text("operator data", encoding="utf-8")

    rc = onboard_adapter.onboard(["--start-over", run_id, "--yes"])

    assert rc == 2
    assert "identity changed" in capsys.readouterr().err
    assert (checkout / "keep.txt").read_text(encoding="utf-8") == "operator data"
    assert original.is_dir()


def test_use_different_folder_refuses_existing_local_checkout(
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

    rc = onboard_adapter.onboard([
        "--use-different-folder", run_id, "--yes",
    ])

    assert rc == 2
    assert "no run-created checkout Yoke can preserve" in capsys.readouterr().err
    assert checkout.is_dir()
