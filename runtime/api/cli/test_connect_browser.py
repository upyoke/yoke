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
        lines = [json.loads(line) for line in output.out.splitlines()]
        assert len(lines) == 2
        event, result = lines
        assert result["activated"] is True
        assert event["phase"] == "machine_authorization"
        assert event["browser_attempted"] is False
        assert event["browser_action"]["user_code"] == "K7F2"
        assert event["match_code"] == "K7F2"
        assert "K7F2" in event["approval_hint"]
        assert event["wait"]["silence_expected"] is True
        assert not any(line.lstrip().startswith("{") for line in output.err.splitlines())
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


def test_json_sign_in_line_reaches_stdout_before_the_first_poll(monkeypatch, capsys):
    _stub_authorization(monkeypatch, capsys, [])
    seen = []
    credential = auth.HostedMachineCredential(
        "https://team.example", "team", "private-token"
    )

    def first_poll(*_args, **_kwargs):
        seen.append(capsys.readouterr())
        return credential

    monkeypatch.setattr(auth, "complete", first_poll)
    assert command.connect(["--json"]) == 0
    event = json.loads(seen[0].out)
    assert event["phase"] == "machine_authorization"
    assert event["browser_action"]["user_code"] == "K7F2"
    assert seen[0].err == ""
    assert json.loads(capsys.readouterr().out)["activated"] is True


@pytest.mark.parametrize("flag", ["--token-stdin", "--invite-code-stdin"])
def test_json_paths_without_browser_print_only_the_result(monkeypatch, capsys, flag):
    _stub_authorization(monkeypatch, capsys, [])
    monkeypatch.setattr(
        command.team_server_authorization,
        "sign_in_methods",
        lambda url: command.team_server_authorization.SignInMethods(True, True),
    )
    monkeypatch.setattr(
        command.machine_secrets, "read_stdin_secret", lambda _name: "private-token"
    )
    monkeypatch.setattr(
        command.teammate_invite_redemption,
        "choose_code",
        lambda **kw: "invite-code" if kw["from_stdin"] else None,
    )
    monkeypatch.setattr(
        command.teammate_invite_redemption,
        "redeem",
        lambda *a, **kw: auth.HostedMachineCredential(
            "https://team.example", "team", "private-token"
        ),
    )
    monkeypatch.setattr(
        command.finish_connection.__globals__["machine_registration"],
        "register_this_machine",
        lambda *a, **kw: {"registered": True},
    )
    assert command.connect(["https://team.example", flag, "--json"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["activated"] is True


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


@pytest.fixture(autouse=True)
def isolate_connection_relay(monkeypatch):
    from yoke_cli.config import credential_repair
    from yoke_cli.config import onboard_session_relay as relay

    monkeypatch.setattr(
        relay, "install", lambda **kw: relay.RelayInstallOutcome(True, False)
    )
    # These tests stub connect_server, so no connection is saved to repair.
    monkeypatch.setattr(
        credential_repair, "repair_revoked_connections", lambda *a, **kw: {}
    )
