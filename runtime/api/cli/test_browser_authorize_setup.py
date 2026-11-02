"""Authorization refreshes prerequisites, then holds the human gate for its window."""

import json
from datetime import timedelta
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
        started = browser_human_gate.utc_now()
        monkeypatch.setattr(
            browser_human_gate, "utc_now", lambda: started + timedelta(seconds=3661)
        )
        with pytest.raises(browser_human_gate.HumanGateActiveError) as refused:
            browser_human_gate.refuse_during_human_gate(tmp_path)
        message = str(refused.value)
        for expected in (
            "identity 'default'",
            "project 'project'",
            "PID ",
            "open for 1h 1m 1s",
            "Hand off to steering or the person",
            "finish or close the sign-in window",
            "quit PID",
            "then retry",
        ):
            assert expected in message
        assert "Wait for" not in message
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


@pytest.mark.parametrize("desktop", [False, True])
def test_omitted_identity_refuses_before_runtime_or_window(
    setup, monkeypatch, capsys, desktop
):
    site = dict(site="app", origin="https://app.example", account="admin@example")
    site["probe"] = {"url": "https://app.example/me", "signed_in_status": 200}
    declarations = {"identities": {"admin": {"sites": [site]}}}
    monkeypatch.setattr(
        browser_identities,
        "declared_identities",
        lambda *a, **kwargs: parse_identity_declarations(declarations),
    )
    args = ["--project", "project", "--json"] + (
        ["--desktop-browser"] if desktop else []
    )
    assert command.browser_authorize(args) != 0
    assert "browser_identity_required" in json.loads(capsys.readouterr().out)["error"]
    assert setup == []


@pytest.mark.parametrize("json_mode", [False, True])
def test_machine_progress_carries_match_code_and_approval_hint(capsys, json_mode):
    from yoke_cli.config import setup_browser
    from yoke_cli.config.onboard_wizard_flow_machine_admission import approval_hint

    browser_action = setup_browser.action(
        "https://team.example/machine-approval/K7F2",
        "Return after approval.",
        user_code="K7F2",
    )
    setup_browser.render_progress(
        {
            "phase": "machine_authorization",
            "browser_action": browser_action,
            "expires_in": 600,
            "interval": 2,
            "browser_attempted": False,
        },
        json_mode=json_mode,
    )
    output = capsys.readouterr()
    assert output.out == ""
    if json_mode:
        event = json.loads(output.err)
        assert event["match_code"] == "K7F2"
        assert event["approval_hint"] == approval_hint("K7F2")
        assert event["browser_action"] == browser_action
        assert event["wait"]["max_seconds"] == 600
    else:
        assert "Match code: K7F2" in output.err
        assert approval_hint("K7F2") in output.err
    setup_browser.render_progress(
        {"phase": "device_browser", "browser_action": browser_action},
        json_mode=json_mode,
    )
    github = capsys.readouterr().err
    assert "approval_hint" not in github and "Match code" not in github


@pytest.mark.parametrize("explicit_url", [False, True])
def test_signed_in_identity_opens_only_for_explicit_url(
    setup, monkeypatch, capsys, explicit_url
):
    declarations = {"identities": {"admin": {"sites": [{
        "site": "app", "origin": "https://app.example", "account": "admin@example",
        "probe": {"url": "https://app.example/me", "signed_in_status": 200},
    }]}}}
    monkeypatch.setattr(
        browser_identities, "declared_identities",
        lambda *a, **kw: parse_identity_declarations(declarations),
    )
    monkeypatch.setattr(command, "check_sign_in", lambda *a: [{
        "site": "app", "state": "signed_in", "origin": "https://app.example",
    }])
    url = "https://app.example/confirm-access"
    windows = []
    monkeypatch.setattr(
        command, "_sign_in_window",
        lambda runtime, profile, urls, json_mode: windows.append(urls) or 0,
    )
    args = ["--project", "project", "--identity", "admin", "--json"]
    assert command.browser_authorize(args + (["--url", url] if explicit_url else [])) == 0
    assert windows == ([[url]] if explicit_url else [])
    assert json.loads(capsys.readouterr().out)["ok"] is True


@pytest.mark.parametrize("started_at, elapsed", [
    ("invalid", "an unknown duration (invalid started_at)"),
    ("2100-01-01T00:00:00Z", "0h 0m 0s"),
])
def test_gate_handoff_survives_invalid_or_future_start(
    monkeypatch, tmp_path, started_at, elapsed
):
    monkeypatch.setattr(browser_human_gate, "active_human_gate", lambda _: {
        "pid": 123, "identity": "buyer", "project": "shop", "started_at": started_at,
    })
    with pytest.raises(browser_human_gate.HumanGateActiveError) as refused:
        browser_human_gate.refuse_during_human_gate(tmp_path)
    assert f"open for {elapsed}" in str(refused.value)
    assert "Hand off to steering or the person" in str(refused.value)
    assert "quit PID 123" in str(refused.value)
