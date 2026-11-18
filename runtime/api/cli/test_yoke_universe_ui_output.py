"""Browser admission stays private in every UI command output mode."""

from __future__ import annotations

import json

import pytest

from yoke_cli.commands import universe_ui as commands
from yoke_cli.config.hosted_machine_browser import BrowserOpenResult
from yoke_cli.config import browser_admission as admission


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("mode", ["local", "self-host"])
@pytest.mark.parametrize(
    "outcome",
    ["opened", "disabled", "agent", "unregistered-agent", "headless", "exception"],
)
def test_admission_only_reaches_human_browser(
    monkeypatch, capsys, json_mode, mode, outcome
):
    secret = "private-admission-secret"
    url = (
        f"http://127.0.0.1:8688/?token={secret}"
        if mode == "local"
        else f"https://team.example/auth/browser-sign-in#selector.{secret}"
    )
    report = {
        "mode": mode,
        "env": "test",
        "running": True,
        "serving": True,
        "pid": 1234,
        "private_url": url,
    }
    monkeypatch.setattr(commands, "self_host_report", lambda **_: dict(report))
    monkeypatch.setattr(
        admission,
        "_resolve_session_id",
        lambda: "agent-session" if outcome == "agent" else None,
    )
    monkeypatch.setattr(
        admission,
        "nearest_harness_family",
        lambda: "codex" if outcome == "unregistered-agent" else None,
    )
    seen = []

    def open_browser(admission):
        seen.append(admission)
        if outcome == "exception":
            raise OSError(f"could not open {admission}")
        return BrowserOpenResult(
            opened=outcome == "opened",
            reason=f"browser_display_unavailable: {admission}",
        )

    monkeypatch.setattr(commands, "open_url", open_browser)
    args = ["--json"] if json_mode else []
    if outcome == "disabled":
        args.append("--no-browser")
    assert commands.ui_up(args) == (1 if outcome in {"headless", "exception"} else 0)
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert secret not in output
    assert url not in output
    assert "private_url" not in output
    assert "read-only" not in output
    assert seen == (
        [] if outcome in {"disabled", "agent", "unregistered-agent"} else [url]
    )
    expected_reason = {
        "headless": "browser_display_unavailable",
        "exception": "browser_open_failed",
        "agent": "browser_agent_mode",
        "unregistered-agent": "browser_agent_mode",
        "disabled": "browser_open_disabled",
    }.get(outcome)
    if outcome == "disabled":
        assert "Run `yoke ui up`" not in output
    elif expected_reason and not json_mode:
        assert f"{expected_reason}: Run `yoke ui up`" in output
    if json_mode:
        result = json.loads(captured.out)
        assert result["browser_opened"] is (outcome == "opened")
        assert result["ok"] is (outcome not in {"headless", "exception"})
        assert result.get("browser_reason") == expected_reason
        assert ("recovery" in result) is (outcome not in {"opened", "disabled"})


@pytest.mark.parametrize("json_mode", [False, True])
def test_down_cannot_print_an_admission_url(monkeypatch, capsys, json_mode):
    monkeypatch.setattr(
        commands.daemon,
        "down",
        lambda: {"stopped": False, "private_url": "http://localhost/?token=secret"},
    )
    assert commands.ui_down(["--json"] if json_mode else []) == 0
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "private_url" not in output
