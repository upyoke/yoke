"""Token-link authorization stores an ordinary browser session without a window."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_cli.commands import browser_authorize, browser_authorize_self_host
from yoke_cli.config import browser_profile, browser_profile_cookies
from yoke_cli.config import self_host_browser_sign_in as exchange
from yoke_contracts.browser_identity import parse_identity_declarations
from yoke_contracts.browser_sign_in import BROWSER_SIGN_IN_REDEEM_PATH
from yoke_harness import browser_automatic_sign_in as automatic
from yoke_harness import browser_human_gate, browser_identity_check

ORIGIN = "https://self-host.example"
CODE = "selector.one-time-secret"
LINK = ORIGIN + BROWSER_SIGN_IN_REDEEM_PATH + "#" + CODE
TOKEN = "synthetic-api-credential"


@pytest.fixture()
def setup(monkeypatch, tmp_path):
    declaration = {
        "site": "yoke",
        "origin": ORIGIN,
        "probe": {"url": ORIGIN + "/", "signed_in_selector": "[data-user]"},
        "sign_in": {"mode": "token-link"},
    }
    connection = {"transport": "https", "api_url": ORIGIN + "/v1"}
    runtime = SimpleNamespace(
        runtime_dir=tmp_path, node=tmp_path / "node", env={"DEBUG": "pw:api"}
    )
    seen = []
    monkeypatch.setattr(exchange.machine_config, "active_connection", lambda: connection)
    monkeypatch.setattr(exchange, "resolve_token", lambda _: TOKEN)

    def request(req, **kwargs):
        seen.append(req.method)
        if req.method == "GET":
            return SimpleNamespace(payload={"auth_method": "token"})
        assert req.get_header("Authorization") == f"Bearer {TOKEN}"
        assert kwargs["replay_safe"] is False
        return SimpleNamespace(payload={
            "auth_method": "token", "sign_in_path": LINK.removeprefix(ORIGIN),
        })

    def resolve(*args):
        identity = parse_identity_declarations(
            {"identities": {"operator": {"sites": [declaration]}}}
        )["operator"]
        return "demo", identity

    monkeypatch.setattr(exchange, "request_json", request)
    monkeypatch.setattr(browser_authorize, "resolve_identity_target", resolve)
    monkeypatch.setattr(browser_authorize, "prepare_browser_runtime", lambda _: runtime)
    monkeypatch.setattr(
        browser_authorize, "check_sign_in",
        lambda *args: [{"site": "yoke", "state": "expired", "detail": "signed out"}],
    )
    window = Mock(side_effect=AssertionError("token authorization opened a window"))
    monkeypatch.setattr(browser_authorize, "_sign_in_window", window)
    monkeypatch.setattr(browser_human_gate, "refuse_during_human_gate", lambda _: None)
    monkeypatch.setattr(browser_identity_check, "stop_profile_daemon", Mock())
    monkeypatch.setattr(browser_profile, "authorized_profile_dir", lambda *a, **k: None)
    monkeypatch.setattr(browser_profile, "ensure_profile_dir", lambda *a, **k: tmp_path)
    monkeypatch.setattr(browser_profile_cookies, "keep_sign_in_cookies", Mock())
    return SimpleNamespace(
        declaration=declaration, seen=seen, window=window, connection=connection
    )


def _authorize():
    return browser_authorize.browser_authorize(
        ["--project", "demo", "--identity", "operator", "--json"]
    )


@pytest.mark.parametrize("state, expected", [
    ("signed_in", 0),
    ("browser_sign_in_expired", 1),
    ("browser_sign_in_used", 1),
    ("https://self-host.example/#" + CODE, 1),
])
def test_link_only_crosses_private_manifest(setup, monkeypatch, capsys, state, expected):
    manifests = []

    def run(argv, *, env, **kwargs):
        assert setup.seen == ["GET", "POST"]
        assert all(secret not in json.dumps([argv, env]) for secret in (TOKEN, CODE))
        assert "DEBUG" not in env
        assert kwargs["capture_output"]
        manifest = Path(argv[-1])
        if os.name != "nt":
            assert manifest.stat().st_mode & 0o777 == 0o600
        manifests.append(manifest)
        assert json.loads(manifest.read_text())["sites"][0]["token_link"] == LINK
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"sites": [{"site": "yoke", "state": state, "detail": LINK}]}),
            stderr=LINK,
        )

    monkeypatch.setattr(automatic.subprocess, "run", run)
    assert _authorize() == expected
    out, err = capsys.readouterr()
    assert all(secret not in out + err for secret in (TOKEN, CODE))
    report = json.loads(out)
    if not expected:
        assert report["sites"][0]["state"] == "signed_in"
        assert report["window_opened"] is False
    else:
        reason = state if state.startswith("browser_sign_in_") else "browser_token_link_sign_in_failed"
        assert report["error"].startswith(reason + ":")
        assert "yoke browser authorize" in report["error"]
    assert len(manifests) == 1 and not manifests[0].exists()
    setup.window.assert_not_called()


@pytest.mark.parametrize("scenario, reason", [
    ("no-connection", "browser_sign_in_self_host_required"),
    ("site-origin", "browser_sign_in_origin_mismatch"),
    ("probe-origin", "browser_sign_in_origin_mismatch"),
    ("oidc-discovery", "browser_sign_in_oidc_required"),
    ("oidc-exchange", "browser_sign_in_oidc_required"),
])
def test_named_refusals_without_browser(setup, monkeypatch, capsys, scenario, reason):
    match scenario:
        case "no-connection":
            monkeypatch.setattr(browser_authorize_self_host, "self_host_connection", lambda: None)
        case "site-origin":
            setup.declaration["origin"] = "https://other.example"
        case "probe-origin":
            setup.declaration["probe"]["url"] = "https://other.example"
        case "oidc-discovery":
            monkeypatch.setattr(
                exchange, "request_json",
                lambda *a, **k: SimpleNamespace(payload={"auth_method": "oidc"}),
            )
        case "oidc-exchange":
            monkeypatch.setattr(
                exchange, "request_json",
                lambda req, **k: SimpleNamespace(
                    payload={"auth_method": "oidc" if req.method == "POST" else "token"},
                ),
            )
    run = Mock(side_effect=AssertionError("refused site reached browser"))
    monkeypatch.setattr(automatic.subprocess, "run", run)
    assert _authorize() != 0
    assert json.loads(capsys.readouterr().out)["error"].startswith(reason + ":")
    run.assert_not_called()
    setup.window.assert_not_called()
