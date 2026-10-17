"""Desktop authorization is additive and asks the operator only for expired sites."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from yoke_cli.commands import browser_authorize_desktop as command
from yoke_contracts.browser_identity import BrowserIdentity, SignInCheck
from yoke_harness import desktop_browser_sign_in as native


@pytest.fixture
def desktop(monkeypatch):
    from yoke_harness import browser_human_gate

    state = {"windows": [], "replies": []}
    identity = BrowserIdentity(
        "admin",
        (
            SignInCheck(
                "prod",
                "https://app.example",
                "https://app.example/auth/sign-in",
                signed_in_status=303,
                account="person@example.com",
            ),
        ),
    )
    monkeypatch.setattr(
        command, "resolve_identity_target", lambda *args: ("acme", identity)
    )
    monkeypatch.setattr(
        command,
        "prepare_browser_runtime",
        lambda *args: SimpleNamespace(runtime_dir="runtime"),
    )
    monkeypatch.setattr(
        browser_human_gate, "human_gate", lambda *args, **kwargs: nullcontext([])
    )
    monkeypatch.setattr(native, "browser_kind", lambda: "Chromium")
    monkeypatch.setattr(
        native, "check_desktop", lambda *args, **kw: state["replies"].pop(0)
    )
    monkeypatch.setattr(
        native,
        "sign_in_window",
        lambda kind, urls: state["windows"].append((kind, urls)),
    )
    return state


def site(state):
    return [
        {
            "site": "prod",
            "state": state,
            "origin": "https://app.example",
            "account": "person@example.com",
        }
    ]


def run(**changes):
    return command.authorize_desktop(
        SimpleNamespace(
            project="acme",
            identity="admin",
            declarations_json="{}",
            reset=False,
            json_mode=True,
            **changes,
        )
    )


def test_signed_in_desktop_opens_nothing(desktop, capsys):
    desktop["replies"] = [site("signed_in")]
    assert run() == 0
    assert desktop["windows"] == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["window_opened"] is False and payload["kept_live_through_reset"]


def test_only_expired_sites_open_then_recheck(desktop, capsys):
    desktop["replies"] = [site("expired"), site("signed_in")]
    assert run() == 0
    assert desktop["windows"] == [("Chromium", ["https://app.example"])]
    assert json.loads(capsys.readouterr().out)["window_opened"]


def test_unreachable_check_never_opens_a_sign_in_window(desktop, capsys):
    desktop["replies"] = [site("unreachable")]
    assert run() == 1
    assert desktop["windows"] == []
    assert "site_unreachable" in json.loads(capsys.readouterr().out)["error"]


def test_desktop_never_wipes_profile(desktop, capsys):
    args = SimpleNamespace(
        project="acme",
        identity="admin",
        declarations_json="{}",
        reset=True,
        json_mode=True,
    )
    assert command.authorize_desktop(args) == 1
    assert "reset_refused" in json.loads(capsys.readouterr().out)["error"]
    assert desktop["windows"] == []


def test_still_signed_out_is_failure(desktop, capsys):
    desktop["replies"] = [site("expired"), site("expired")]
    assert run() == 1
    assert "sign_in_incomplete" in json.loads(capsys.readouterr().out)["error"]


def test_combined_remote_command_keeps_automation_reset_and_never_resets_desktop(
    monkeypatch, capsys
):
    from yoke_cli.commands import browser_authorize

    calls = []

    def automation(args):
        calls.append(args)
        print('{"ok":true,"identity":"admin"}')
        return 0

    def desktop(parsed):
        calls.append(parsed.reset)
        print('{"ok":true,"browser":"Safari"}')
        return 0

    monkeypatch.setattr(browser_authorize, "browser_authorize", automation)
    monkeypatch.setattr(command, "authorize_desktop", desktop)
    parsed = SimpleNamespace(json_mode=True, reset=True)
    assert (
        command.authorize_with_desktop(
            parsed, ["--json", "--reset", "--include-desktop-browser"]
        )
        == 0
    )
    assert calls == [["--json", "--reset"], False]
    assert json.loads(capsys.readouterr().out)["desktop_browser"]["browser"] == "Safari"
