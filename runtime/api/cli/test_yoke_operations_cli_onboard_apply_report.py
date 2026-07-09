from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_wizard
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING
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


def test_apply_report_writes_statuses_and_redacts_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "config_path": "/tmp/home/config.json",
            "env_name": "stage",
            "api_url": "https://api.stage.upyoke.com",
            "token_source_kind": "prompt",
        },
    )

    writer.step_started("create-or-validate-dir", "/tmp/home")
    writer.step_done("create-or-validate-dir", "/tmp/home")
    writer.fail(RuntimeError(
        "Authorization: Bearer ghp_secret token=supersecret "
        "https://octo:ghp_urlsecret@github.com/acme/widget.git"
    ))

    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    assert payload["schema"] == onboard_apply_report.SCHEMA_NAME
    assert payload["final_status"] == "failed"
    assert payload["steps"][0]["status"] == "done"
    assert payload["steps"][1]["status"] == "failed"
    serialized = json.dumps(payload)
    assert "ghp_secret" not in serialized
    assert "supersecret" not in serialized
    assert "ghp_urlsecret" not in serialized


def test_sanitize_text_redacts_url_embedded_credentials() -> None:
    redacted = onboard_apply_report.sanitize_text(
        "fatal: Authentication failed for "
        "https://octo:ghp_urlsecret@github.com/acme/widget.git?token=supersecret"
    )

    assert "ghp_urlsecret" not in redacted
    assert "supersecret" not in redacted
    assert (
        "https://octo:<redacted>@github.com/acme/widget.git?token=<redacted>"
        in redacted
    )


def test_sanitize_text_redacts_token_assignment_variants() -> None:
    redacted = onboard_apply_report.sanitize_text(
        "failed with token = ghp_spaced, token:ghp_colon; token=ghp_plain"
    )

    assert "ghp_spaced" not in redacted
    assert "ghp_colon" not in redacted
    assert "ghp_plain" not in redacted
    assert "token = <redacted>" in redacted
    assert "token:<redacted>" in redacted
    assert "token=<redacted>" in redacted


def test_adapter_converts_apply_failure_to_typed_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))

    def fake_build_report(**kwargs):
        if kwargs.get("apply"):
            raise onboard_adapter.onboard_config.OnboardError(
                "Authorization: token ghp_secret"
            )
        return _preview()

    monkeypatch.setattr(onboard_adapter.onboard_config, "build_report", fake_build_report)

    with pytest.raises(onboard_wizard.WizardApplyError) as raised:
        onboard_adapter._apply_with_durable_report({
            "config_path": "/tmp/home/config.json",
            "env_name": "stage",
            "api_url": "https://api.stage.upyoke.com",
            "token": "yoke-secret",
            "token_source_kind": "prompt",
            "mode": "quick",
            "apply": True,
            "check_identity": True,
            "project_mode": "machine-only",
        })

    assert raised.value.report_path
    payload = json.loads(Path(raised.value.report_path).read_text(encoding="utf-8"))
    assert payload["final_status"] == "failed"
    assert raised.value.failed_step == payload["failed_step"]
    assert "ghp_secret" not in json.dumps(payload)


def test_noninteractive_failure_prints_report_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))

    def fake_build_report(**kwargs):
        if kwargs.get("apply"):
            raise onboard_adapter.onboard_config.OnboardError("repo already exists")
        return _preview()

    monkeypatch.setattr(onboard_adapter.onboard_config, "build_report", fake_build_report)

    report = onboard_adapter._build_report(
        config_path="/tmp/home/config.json",
        env_name="stage",
        api_url="https://api.stage.upyoke.com",
        token="yoke-secret",
        token_file=None,
        token_source_kind="argument",
        mode="quick",
        apply=True,
        check_identity=True,
        machine_github_choice="skip",
        machine_github_api_url=None,
        machine_github_token=None,
        machine_github_token_file=None,
        machine_github_token_source_kind=None,
        project_mode="machine-only",
        project_remote_url=None,
        project_checkout=None,
        project_slug=None,
        project_name=None,
        project_org=None,
        project_github_repo=None,
        project_default_branch=None,
        project_default_branch_source=None,
        project_public_item_prefix=None,
        existing_project_id=None,
        project_github_adoption=None,
        project_github_token=None,
        project_github_token_file=None,
        project_github_token_stdin_value=None,
    )

    assert report is None
    err = capsys.readouterr().err
    assert "error: repo already exists" in err
    assert "failed step:" in err
    assert "report:" in err
    assert "resume:" in err
    assert "yoke-secret" not in err


def test_noninteractive_machine_config_write_failure_prints_report_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"

    def fail_set_connection(*_args, **_kwargs):
        raise onboard_adapter.MachineConfigWriteError(
            "couldn't write machine config"
        )

    monkeypatch.setattr(
        onboard_adapter.onboard_config.writer,
        "set_connection",
        fail_set_connection,
    )

    rc = onboard_adapter.onboard([
        "--config", str(config),
        "--env", "stage",
        "--api-url", "https://api.stage.upyoke.com",
        "yoke-secret",
        "--yes",
        "--json",
        "--skip-identity-check",
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: couldn't write machine config" in captured.err
    assert "failed step:" in captured.err
    assert "report:" in captured.err
    assert "resume:" in captured.err
    assert "yoke-secret" not in captured.err

    report_line = next(
        line for line in captured.err.splitlines() if line.startswith("report: ")
    )
    report_path = Path(report_line.removeprefix("report: ").strip())
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["final_status"] == "failed"
    assert payload["failed_step"]
    assert payload["resume_command"].startswith("yoke onboard --resume ")
    assert "yoke-secret" not in json.dumps(payload)


def test_apply_failure_outside_onboard_error_finalizes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-OnboardError apply failure (the GitHub repo-collision class) still
    stamps the report failed and surfaces a typed WizardApplyError.

    The real apply raises github_publish.GitHubPublishError on a repo collision —
    neither an OnboardError nor a MachineConfig* error. It must not escape the
    report writer and orphan the run at "running".
    """
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))

    class _PublishLikeError(RuntimeError):
        pass

    def fake_build_report(**kwargs):
        if kwargs.get("apply"):
            raise _PublishLikeError(
                "a repo named o/r already exists and has content"
            )
        return _preview()

    monkeypatch.setattr(onboard_adapter.onboard_config, "build_report", fake_build_report)

    with pytest.raises(onboard_wizard.WizardApplyError) as raised:
        onboard_adapter._apply_with_durable_report({
            "config_path": "/tmp/home/config.json",
            "env_name": "stage",
            "api_url": "https://api.stage.upyoke.com",
            "token": "yoke-secret",
            "token_source_kind": "prompt",
            "mode": "quick",
            "apply": True,
            "check_identity": True,
            "project_mode": "machine-only",
        })

    assert raised.value.report_path
    assert raised.value.resume_command
    payload = json.loads(Path(raised.value.report_path).read_text(encoding="utf-8"))
    assert payload["final_status"] == "failed"
    assert payload["failed_step"]  # a step was attributed, not left null
    assert not any(s["status"] == "running" for s in payload["steps"])  # no orphan


def test_report_resume_hints_reference_real_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "config_path": "/tmp/home/config.json",
            "env_name": "stage",
            "api_url": "https://api.stage.upyoke.com",
            "token_source_kind": "prompt",
            "project_checkout": "/home/u/code/widget",
        },
    )
    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    assert payload["resume_command"] == f"yoke onboard --resume {payload['run_id']}"
    assert "--start-over" not in json.dumps(payload)
    assert "/home/u/code/widget" in payload["start_over_hint"]


def test_fail_leaves_no_step_orphaned_at_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_report can mark a coarse pair running together before a blocking
    call; on failure the last running step is the failure point and the earlier
    one is done — never left stuck at running."""
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    preview = {
        "plan": {"project": {"name": "widget"}, "steps": [
            {"action": "project-source-choice", "target": "create-repo:"},
            {"action": "project-create-checkout", "target": "/home/u/code/widget"},
        ]},
    }
    writer = onboard_apply_report.ApplyReportWriter.start(preview, {})
    writer.step_started("project-source-choice", "create-repo:")
    writer.step_started("project-create-checkout", "/home/u/code/widget")
    writer.fail(RuntimeError("create failed"))

    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    statuses = {s["step_id"]: s["status"] for s in payload["steps"]}
    assert "running" not in statuses.values()
    assert payload["final_status"] == "failed"
    # The later (deeper) step is the attributed failure; the earlier handed off.
    assert statuses["00-project-source-choice"] == "done"
    assert statuses["01-project-create-checkout"] == "failed"
    assert payload["failed_step"] == "01-project-create-checkout"


def test_apply_report_carries_replay_safe_input_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "fresh-checkout"
    publish = PublishRequest(
        owner="octo-org",
        name="widget",
        user_login="octocat",
        token="publish-secret",
        api_url="https://api.github.example",
        private=True,
    )
    clone = ClonePlan(
        outcome="make-it-mine",
        keep_upstream=True,
        publish=publish,
        fallback_token="clone-secret",
        fork_api_url="https://api.github.example",
    )

    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "config_path": "/tmp/home/config.json",
            "env_name": "stage",
            "api_url": "https://api.stage.upyoke.com",
            "token": "yoke-secret",
            "token_source_kind": "argument",
            "machine_github_choice": "store-token",
            "machine_github_token": "machine-gh-secret",
            "machine_github_token_source_kind": "file",
            "machine_github_token_file": "/tmp/machine-gh-token",
            "project_mode": "clone-remote",
            "project_remote_url": "https://github.com/octo/source.git",
            "project_checkout": str(checkout),
            "project_slug": "widget",
            "project_name": "Widget",
            "project_github_repo": "octo-org/widget",
            "project_default_branch": "main",
            "project_public_item_prefix": "WIDG",
            "project_github_adoption": GITHUB_ADOPTION_APP_BINDING,
            "project_github_token": None,
            "project_github_token_file": None,
            "project_clone": clone,
        },
    )

    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    snapshot = payload["input_snapshot"]
    assert snapshot["env_name"] == "stage"
    assert snapshot["project"]["slug"] == "widget"
    assert snapshot["project"]["clone"]["outcome"] == "make-it-mine"
    assert snapshot["project"]["clone"]["publish"]["owner"] == "octo-org"
    assert snapshot["checkout_provenance"] == {
        "path": str(checkout),
        "project_mode": "clone-remote",
        "existed_before_apply": False,
        "created_by_run": True,
        "safe_to_remove_on_start_over": True,
    }
    serialized = json.dumps(payload)
    assert "yoke-secret" not in serialized
    assert "machine-gh-secret" not in serialized
    assert "publish-secret" not in serialized
    assert "clone-secret" not in serialized


def test_local_checkout_snapshot_is_not_safe_to_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "existing"
    checkout.mkdir()
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {
            "project_mode": "local-checkout",
            "project_checkout": str(checkout),
        },
    )

    payload = json.loads(Path(writer.summary()["path"]).read_text(encoding="utf-8"))
    provenance = payload["input_snapshot"]["checkout_provenance"]
    assert provenance["existed_before_apply"] is True
    assert provenance["created_by_run"] is False
    assert provenance["safe_to_remove_on_start_over"] is False
