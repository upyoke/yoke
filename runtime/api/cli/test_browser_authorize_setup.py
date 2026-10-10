"""Authorization refreshes prerequisites, then holds the human gate for its window."""

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.browser_identity import parse_identity_declarations
from yoke_cli.commands import browser_authorize as command
from yoke_cli.commands import browser_sign_in
from yoke_cli.config import browser_identities, browser_profile
from yoke_harness import browser_human_gate, browser_runtime_home, browser_setup


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/authorize.js").write_text("")
    events = []
    toolchain = SimpleNamespace(node="/node", command_env=lambda: {"DISPLAY": ":10"})
    monkeypatch.setattr(browser_runtime_home, "ensure_materialized", lambda: tmp_path)
    monkeypatch.setattr(
        browser_sign_in.browser_node_toolchain,
        "ensure_node_toolchain",
        lambda: toolchain,
    )
    monkeypatch.setattr(
        browser_profile, "profile_project_key", lambda value, **kwargs: "project"
    )
    monkeypatch.setattr(
        browser_identities,
        "declared_identities",
        lambda key, **kwargs: parse_identity_declarations({}),
    )
    monkeypatch.setattr(
        browser_profile, "ensure_profile_dir", lambda value, **kw: tmp_path / "profile"
    )
    monkeypatch.setattr(command, "keep_sign_in_cookies", lambda profile: 0)
    monkeypatch.setattr(
        browser_human_gate,
        "stop_automated_daemons",
        lambda client, runtime_dir: events.append("stop") or [],
    )

    def provision(browser, selected, *, emit):
        assert browser == tmp_path and selected is toolchain
        events.append("setup")
        emit("sandbox verified")
        return selected.command_env()

    def launch(argv, **kwargs):
        events.append("window")
        assert kwargs["env"]["DISPLAY"] == ":10"
        # No automated browser may start while the person signs in.
        with pytest.raises(browser_human_gate.HumanGateActiveError):
            browser_human_gate.refuse_during_human_gate(tmp_path)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(browser_setup, "ensure_browser_runtime", provision)
    monkeypatch.setattr(command.subprocess, "run", launch)
    return events


def test_authorization_provisions_before_window_and_keeps_json_clean(
    setup, tmp_path, capsys
):
    assert command.browser_authorize(["--project", "project", "--json"]) == 0
    assert setup == ["setup", "stop", "window"]
    output = capsys.readouterr()
    assert json.loads(output.out)["ok"] is True
    assert "sandbox verified" in output.err
    assert browser_human_gate.active_human_gate(tmp_path) is None


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
