"""Connect opens approval only in a person's terminal, after a visible notice."""

import json
import sys

import pytest

from yoke_cli.commands import connect as command
from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config.hosted_machine_browser import BrowserOpenResult

URL = "https://app.upyoke.com/connect?user_code=K7F2"


@pytest.mark.parametrize("self_host", [False, True])
@pytest.mark.parametrize(
    "stdin_tty,stdout_tty,json_mode,session,family,should_open",
    [
        (True, True, False, None, None, True),
        (False, True, False, None, None, False),
        (True, False, False, None, None, False),
        (True, True, True, None, None, False),
        (True, True, False, "agent-session", None, False),
        (True, True, False, None, "claude-code", False),
        (True, True, False, None, "codex", False),
        (True, True, False, None, "cursor", False),
    ],
)
def test_connect_approval_opens_only_in_human_terminal(
    monkeypatch,
    capsys,
    self_host,
    stdin_tty,
    stdout_tty,
    json_mode,
    session,
    family,
    should_open,
):
    opened = []
    pending = _stub_authorization(monkeypatch, capsys, opened)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin_tty)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout_tty)
    monkeypatch.setattr(command, "_resolve_session_id", lambda: session)
    monkeypatch.setattr(command, "running_harness_family", lambda: family)
    if self_host:
        monkeypatch.setattr(
            command.team_server_authorization,
            "sign_in_methods",
            lambda url: command.team_server_authorization.SignInMethods(True, True),
        )
    args = ["https://team.example"] if self_host else []
    if json_mode:
        args.append("--json")
    assert command.connect(args) == 0
    output = capsys.readouterr()
    assert opened == ([pending.verification_uri_complete] if should_open else [])
    assert URL in output.out + output.err
    assert "device-secret" not in output.out + output.err
    assert "private-token" not in output.out + output.err
    if json_mode:
        assert json.loads(output.out)["activated"] is True
        event = json.loads(output.err)
        assert event["browser_attempted"] is False
        assert event["browser_action"]["user_code"] == "K7F2"
    else:
        assert "Match code: K7F2" in output.out
        assert "Waiting by design:" in output.out


@pytest.mark.parametrize("raises", [False, True])
def test_connect_browser_failure_keeps_link_and_recovery(monkeypatch, capsys, raises):
    _stub_authorization(monkeypatch, capsys, [])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(command, "_resolve_session_id", lambda: None)
    monkeypatch.setattr(command, "running_harness_family", lambda: None)

    def fail(url):
        if raises:
            raise OSError("no display")
        return BrowserOpenResult(False, reason="browser_display_unavailable")

    monkeypatch.setattr(command.setup_browser, "open_url", fail)
    assert command.connect([]) == 0
    output = capsys.readouterr().out
    assert URL in output
    assert (
        "browser_open_failed" in output
        if raises
        else "browser_display_unavailable" in output
    )
    assert "open the URL above yourself" in output


def _stub_authorization(monkeypatch, capsys, opened):
    pending = auth.PendingMachineAuthorization(
        "https://app.upyoke.com",
        "device-secret",
        "K7F2",
        "https://app.upyoke.com/connect",
        URL,
        60,
        2,
    )
    monkeypatch.setattr(auth, "start", lambda *a, **kw: pending)
    monkeypatch.setattr(
        auth,
        "complete",
        lambda *a, **kw: auth.HostedMachineCredential(
            "https://team.example", "team", "private-token"
        ),
    )

    def open_browser(url):
        # The notice and usable link have reached stdout before the native opener.
        before = capsys.readouterr()
        assert command.setup_browser.OPENING_NOTICE in before.out
        assert URL in before.out
        opened.append(url)
        return BrowserOpenResult(True, method="test")

    monkeypatch.setattr(command.setup_browser, "open_url", open_browser)
    monkeypatch.setattr(
        command.server_connect,
        "connect_server",
        lambda *a, **kw: {
            "api_url": "https://team.example",
            "env": "team",
            "activated": True,
        },
    )
    return pending
