"""Automatic authorize never opens a window; verify never signs in."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.api.domain.test_browser_automatic_sign_in import declaration, identity
from yoke_cli.commands import browser_authorize, browser_verify
from yoke_cli.commands.adapters.projects_secret import projects_capability_secret_set
from yoke_harness import browser_automatic_sign_in as automatic
from yoke_contracts.browser_identity import parse_identity_declarations


@pytest.fixture
def target(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    runtime = SimpleNamespace(runtime_dir=tmp_path, node=tmp_path / "node", env={})
    buyer = identity()
    for module in (browser_authorize, browser_verify):
        monkeypatch.setattr(
            module, "resolve_identity_target", lambda *a: ("acme", buyer)
        )
        monkeypatch.setattr(module, "prepare_browser_runtime", lambda *a: runtime)
        monkeypatch.setattr(
            module,
            "check_sign_in",
            lambda *a: [{"site": "shop", "state": "expired", "detail": "-"}],
        )
    window = Mock(side_effect=AssertionError("automatic sign-in opened a window"))
    monkeypatch.setattr(browser_authorize, "_sign_in_window", window)
    return buyer, window


def test_authorize_automatic_site_needs_no_human_gate_or_window(
    target, monkeypatch, capsys
):
    buyer, window = target
    sign_in = Mock(return_value=[{"site": "shop", "state": "signed_in", "detail": "-"}])
    monkeypatch.setattr(
        "yoke_cli.commands.browser_authorize_automatic.sign_in_expired_sites", sign_in
    )
    assert (
        browser_authorize.browser_authorize(
            ["--project", "acme", "--identity", "buyer", "--json"]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and result["window_opened"] is False
    assert result["sites"][0]["state"] == "signed_in"
    assert sign_in.call_args.args[3] == buyer
    window.assert_not_called()


def test_verify_automatic_site_is_read_only(target, monkeypatch, capsys):
    sign_in = Mock(side_effect=AssertionError("verify typed credentials"))
    monkeypatch.setattr(automatic, "sign_in_expired_sites", sign_in)
    assert (
        browser_verify.browser_verify(
            ["--project", "acme", "--identity", "buyer", "--json"]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["sites"][0]["state"] == "expired"
    sign_in.assert_not_called()


def test_authorize_reports_named_failure_without_a_window(target, monkeypatch, capsys):
    sign_in = Mock(
        side_effect=automatic.AutomaticSignInError(
            "browser_automatic_sign_in_failed: shop; remove sign_in and run yoke browser authorize"
        )
    )
    monkeypatch.setattr(
        "yoke_cli.commands.browser_authorize_automatic.sign_in_expired_sites", sign_in
    )
    assert browser_authorize.browser_authorize(["--project", "acme", "--json"]) == 1
    assert (
        "browser_automatic_sign_in_failed"
        in json.loads(capsys.readouterr().out)["error"]
    )
    target[1].assert_not_called()


def test_mixed_identity_leaves_only_human_sites_for_window(monkeypatch):
    from yoke_cli.commands.browser_authorize_automatic import authorize_automatic

    human = dict(declaration(), site="google")
    del human["sign_in"]
    buyer = parse_identity_declarations(
        {"identities": {"buyer": {"sites": [declaration(), human]}}}
    )["buyer"]
    sign_in = Mock(
        return_value=[
            {"site": "shop", "state": "signed_in"},
            {"site": "google", "state": "expired"},
        ]
    )
    monkeypatch.setattr(
        "yoke_cli.commands.browser_authorize_automatic.sign_in_expired_sites", sign_in
    )
    _, remaining = authorize_automatic(None, None, "acme", buyer, list(buyer.sites))
    assert [site.site for site in remaining] == ["google"]


def test_secret_set_refuses_positional_value_before_dispatch(capsys):
    secret = "synthetic-password-in-argv-is-refused"
    assert (
        projects_capability_secret_set(
            [
                "--project",
                "acme",
                "--cap-type",
                "browser-control",
                "--key",
                "sign-in.buyer.shop.password",
                secret,
            ]
        )
        == 2
    )
    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert "--value-file" in out.err and "--value-stdin" in out.err


def test_reset_refuses_before_removing_a_profile_while_a_human_signs_in(
    target, monkeypatch, capsys
):
    from yoke_cli.config import browser_profile
    from yoke_harness import browser_human_gate

    removed = Mock()
    monkeypatch.setattr(browser_profile, "remove_profile_dir", removed)
    monkeypatch.setattr(
        browser_human_gate,
        "refuse_during_human_gate",
        Mock(side_effect=RuntimeError("browser_human_gate_active: finish sign-in")),
    )
    assert (
        browser_authorize.browser_authorize(["--project", "acme", "--reset", "--json"])
        == 2
    )
    assert "browser_human_gate_active" in json.loads(capsys.readouterr().out)["error"]
    removed.assert_not_called()
