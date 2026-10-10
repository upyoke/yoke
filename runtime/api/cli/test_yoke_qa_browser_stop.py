"""``yoke qa browser stop`` ends the machine-local daemon."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands.qa_browser_stop import qa_browser_stop


def test_stop_reports_stopped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands.qa_browser_stop.required_project_context",
        lambda project: "yoke",
    )
    monkeypatch.setattr(
        "yoke_cli.config.browser_profile.authorized_profile_dir",
        lambda project, identity: None,
    )

    def _stop(*, profile_dir: str) -> str:
        assert profile_dir == ""
        return "stopped"

    import yoke_harness.browser_client as browser_client

    monkeypatch.setattr(browser_client, "daemon_stop", _stop)
    assert qa_browser_stop(["--project", "yoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "stopped"}


def test_stop_already_down_is_not_running(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands.qa_browser_stop.required_project_context",
        lambda project: "yoke",
    )
    monkeypatch.setattr(
        "yoke_cli.config.browser_profile.authorized_profile_dir",
        lambda project, identity: None,
    )

    def _stop(*, profile_dir: str) -> str:
        raise RuntimeError("daemon not running")

    import yoke_harness.browser_client as browser_client

    monkeypatch.setattr(browser_client, "daemon_stop", _stop)
    assert qa_browser_stop(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_running"


def test_stop_failure_names_status_retry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "yoke_cli.commands.qa_browser_stop.required_project_context",
        lambda project: "yoke",
    )
    monkeypatch.setattr(
        "yoke_cli.config.browser_profile.authorized_profile_dir",
        lambda project, identity: None,
    )

    def _stop(*, profile_dir: str) -> str:
        raise RuntimeError(
            "browser_daemon_profile_mismatch: state belongs to another profile"
        )

    import yoke_harness.browser_client as browser_client

    monkeypatch.setattr(browser_client, "daemon_stop", _stop)
    assert qa_browser_stop([]) == 1
    err = capsys.readouterr().err
    assert "browser_daemon_profile_mismatch" in err
    assert "yoke qa browser status" in err
