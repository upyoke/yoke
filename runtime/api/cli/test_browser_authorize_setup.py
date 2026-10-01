"""Authorization refreshes system/browser prerequisites before the plain window."""

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands import browser_authorize as command
from yoke_cli.config import browser_profile
from yoke_harness import browser_runtime_home, browser_setup


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/authorize.js").write_text("")
    events = []
    toolchain = SimpleNamespace(node="/node", command_env=lambda: {"DISPLAY": ":10"})
    monkeypatch.setattr(browser_runtime_home, "ensure_materialized", lambda: tmp_path)
    monkeypatch.setattr(
        command.browser_node_toolchain, "ensure_node_toolchain", lambda: toolchain
    )
    monkeypatch.setattr(browser_profile, "profile_project_key", lambda value: "project")
    monkeypatch.setattr(
        browser_profile, "ensure_profile_dir", lambda value: tmp_path / "profile"
    )
    monkeypatch.setattr(command, "keep_sign_in_cookies", lambda profile: 0)
    monkeypatch.setattr(
        command, "_stop_daemon_holding_profile", lambda client: events.append("stop")
    )

    def provision(browser, selected, *, emit):
        assert browser == tmp_path and selected is toolchain
        events.append("setup")
        emit("sandbox verified")

    def launch(argv, **kwargs):
        events.append("window")
        assert kwargs["env"]["DISPLAY"] == ":10"
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(browser_setup, "ensure_browser_runtime", provision)
    monkeypatch.setattr(command.subprocess, "run", launch)
    return events


def test_authorization_provisions_before_window_and_keeps_json_clean(setup, capsys):
    assert command.browser_authorize(["--project", "project", "--json"]) == 0
    assert setup == ["setup", "stop", "window"]
    output = capsys.readouterr()
    assert json.loads(output.out)["ok"] is True
    assert "sandbox verified" in output.err


def test_setup_refusal_preserves_profile_and_stops_before_window(
    setup, monkeypatch, capsys
):
    def refuse(*args, **kwargs):
        raise RuntimeError(
            "browser_apparmor_setup_failed: profile cannot load; retry yoke qa browser setup"
        )

    monkeypatch.setattr(browser_setup, "ensure_browser_runtime", refuse)
    assert command.browser_authorize(["--project", "project", "--json", "--reset"]) == 2
    assert setup == []
    assert (
        "browser_apparmor_setup_failed" in json.loads(capsys.readouterr().out)["error"]
    )
