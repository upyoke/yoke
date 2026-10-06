"""Self-host UI routing reuses HTTPS credentials without starting a daemon."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands import universe_ui as commands, universe_ui_remote as remote
from yoke_contracts.browser_sign_in import (
    BROWSER_SIGN_IN_PATH,
    BROWSER_SIGN_IN_REDEEM_PATH,
)
from yoke_contracts.api_urls import HOSTED_PROD_API_URL, HOSTED_STAGE_API_URL


@pytest.fixture()
def setup(monkeypatch, tmp_path):
    token_path = tmp_path / "token"
    token_path.write_text("test-token")
    connection = {
        "transport": "https",
        "api_url": "https://team.example/v1",
        "env": "team",
        "credential_source": {"kind": "token_file", "path": str(token_path)},
    }
    monkeypatch.setattr(remote.machine_config, "active_connection", lambda: connection)

    def no_daemon():
        raise AssertionError("self-host must not start or inspect the local daemon")

    monkeypatch.setattr(commands.daemon, "status", no_daemon)
    return connection


@pytest.mark.parametrize("method", ["token", "oidc"])
def test_up_opens_server_door_with_active_credential(
    setup, monkeypatch, capsys, method
):
    path = (
        BROWSER_SIGN_IN_REDEEM_PATH + "#" + "s" * 16 + "." + "c" * 43
        if method == "token"
        else "/"
    )
    seen = []

    def exchange(request, **kwargs):
        assert request.full_url == "https://team.example" + BROWSER_SIGN_IN_PATH
        if request.get_method() == "GET":
            assert request.get_header("Authorization") is None
            assert kwargs["replay_safe"] is True
            return SimpleNamespace(payload={"auth_method": method})
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer test-token"
        assert kwargs["replay_safe"] is False
        assert kwargs["sensitive_values"] == ("test-token",)
        return SimpleNamespace(payload={"auth_method": method, "sign_in_path": path})

    monkeypatch.setattr(remote, "request_json", exchange)
    monkeypatch.setattr(
        commands.webbrowser, "open", lambda url: seen.append(url) or True
    )
    assert commands.ui_up(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["browser_opened"] is True
    assert report["mode"] == "self-host"
    assert report["private_url"] == "https://team.example" + path
    assert seen == [report["private_url"]]


def test_no_browser_prints_private_link(setup, monkeypatch, capsys):
    path = BROWSER_SIGN_IN_REDEEM_PATH + "#" + "s" * 16 + "." + "c" * 43
    monkeypatch.setattr(
        remote,
        "request_json",
        lambda *_args, **_kwargs: SimpleNamespace(
            payload={"auth_method": "token", "sign_in_path": path}
        ),
    )
    assert commands.ui_up(["--no-browser"]) == 0
    output = capsys.readouterr().out
    assert "https://team.example" + path in output
    assert "single-use" in output


@pytest.mark.parametrize(
    "url",
    [
        HOSTED_PROD_API_URL,
        HOSTED_STAGE_API_URL,
        "https://app.upyoke.com/api/orgs/example",
    ],
)
def test_cloud_keeps_existing_route(setup, url):
    setup["api_url"] = url
    assert remote.self_host_report(host=None, port=None) is None


@pytest.mark.parametrize("args", [["--host", "127.0.0.1"], ["--port", "1234"]])
def test_local_flags_refuse_for_server(setup, capsys, args):
    assert commands.ui_up(args) == 1
    assert "self_host_ui_local_flags" in capsys.readouterr().err


@pytest.mark.parametrize(
    "payload",
    [
        {"auth_method": "token", "sign_in_path": "https://attacker.example/"},
        {"auth_method": "token", "sign_in_path": "//attacker.example"},
        {},
        None,
    ],
)
def test_invalid_server_response_cannot_open_external_url(
    setup, monkeypatch, capsys, payload
):
    monkeypatch.setattr(
        remote,
        "request_json",
        lambda *_args, **_kwargs: SimpleNamespace(payload=payload),
    )
    assert commands.ui_up(["--no-browser"]) == 1
    assert "browser_sign_in_invalid_response" in capsys.readouterr().err


def test_missing_token_names_recovery(setup, monkeypatch, capsys):
    monkeypatch.setattr(
        remote,
        "request_json",
        lambda *_args, **_kwargs: SimpleNamespace(payload={"auth_method": "token"}),
    )
    setup["credential_source"]["path"] += ".missing"
    assert commands.ui_up(["--no-browser"]) == 1
    error = capsys.readouterr().err
    assert "browser_sign_in_credential_unavailable" in error
    assert "yoke auth set" in error


def test_oidc_needs_no_api_token(setup, monkeypatch, capsys):
    setup["credential_source"]["path"] += ".missing"
    monkeypatch.setattr(
        remote,
        "request_json",
        lambda *_args, **_kwargs: SimpleNamespace(payload={"auth_method": "oidc"}),
    )
    assert commands.ui_up(["--no-browser", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["private_url"] == "https://team.example/"
