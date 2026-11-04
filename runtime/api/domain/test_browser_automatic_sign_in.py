"""Credential isolation and automatic Browser case preparation."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    parse_identity_declarations,
)
from yoke_contracts.machine_config.capability_secrets import (
    is_machine_local_capability_secret,
)
from yoke_cli.config.capability_secrets import (
    list_machine_capability_secret_keys,
    store_machine_capability_secret,
)
from yoke_harness import browser_automatic_sign_in as automatic
from yoke_core.domain.browser_qa_automatic_sign_in import prepare_automatic_identities


def declaration():
    return {
        "site": "shop",
        "origin": "https://shop.example",
        "probe": {"url": "https://shop.example/me", "signed_in_status": 200},
        "sign_in": {
            "mode": "automatic",
            "url": "https://shop.example/login",
            "steps": [{"fill": "#password", "secret": "password"}, {"click": "button"}],
        },
    }


def identity(site=None):
    return parse_identity_declarations(
        {"identities": {"buyer": {"sites": [site or declaration()]}}}
    )["buyer"]


def test_parser_preserves_only_nonsecret_steps():
    assert identity().sites[0].sign_in.steps[0] == {
        "fill": "#password",
        "secret": "password",
    }
    site = declaration()
    del site["sign_in"]
    assert identity(site).sites[0].sign_in is None


@pytest.mark.parametrize(
    "plan",
    [
        False,
        {},
        {"mode": "human"},
        {
            "mode": "automatic",
            "url": "https://evil.example/login",
            "steps": [{"click": "b"}],
        },
        {"mode": "automatic", "url": "https://shop.example", "steps": []},
        {
            "mode": "automatic",
            "url": "https://shop.example",
            "steps": [{"fill": "input", "secret": "../password"}],
        },
        {
            "mode": "automatic",
            "url": "https://shop.example",
            "steps": [{"fill": "input", "value": "unsafe"}],
        },
    ],
)
def test_parser_rejects_unsafe_declarations(plan):
    site = declaration()
    site["sign_in"] = plan
    with pytest.raises(BrowserIdentityError):
        identity(site)


@pytest.mark.parametrize(
    "key,local",
    [
        ("sign-in.buyer.shop.password", True),
        ("profile", False),
        ("identities", False),
        ("sign-in.buyer.shop", False),
        ("sign-in.buyer.shop.password/extra", False),
        ("sign-in.Buyer.shop.password", False),
    ],
)
def test_secret_key_predicate(key, local):
    assert is_machine_local_capability_secret("browser-control", key) is local
    assert not is_machine_local_capability_secret("other", key)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(
        automatic.browser_profile, "authorized_profile_dir", lambda *a, **k: profile
    )
    monkeypatch.setattr(
        automatic.browser_profile, "ensure_profile_dir", lambda *a, **k: profile
    )
    monkeypatch.setattr(automatic, "keep_sign_in_cookies", lambda p: 0)
    stopped = Mock()
    monkeypatch.setattr(automatic.checks, "stop_profile_daemon", stopped)
    runtime = SimpleNamespace(node=Path("/node"), runtime_dir=tmp_path, env={})
    states = [{"site": "shop", "state": "expired", "detail": "signed out"}]
    monkeypatch.setattr(automatic.checks, "check_identity", lambda *a, **k: states)
    return runtime, states, stopped


def test_missing_secret_teaches_exact_machine_local_setup(setup):
    runtime, _, stopped = setup
    with pytest.raises(
        automatic.AutomaticSignInError,
        match="browser_sign_in_secret_missing:.*--key sign-in.buyer.shop.password --value-stdin",
    ):
        automatic.sign_in_expired_sites(None, runtime, "acme", identity())
    stopped.assert_called_once()


@pytest.mark.parametrize("success", [True, False])
def test_secret_never_enters_argv_manifest_receipts_or_errors(
    setup, monkeypatch, success, capsys
):
    runtime, _, _ = setup
    secret = "planted-password-never-report"
    key = "sign-in.buyer.shop.password"
    path = store_machine_capability_secret("acme", "browser-control", key, secret)
    assert list_machine_capability_secret_keys("acme", "browser-control") == [key]
    seen = []

    def run(argv, **kwargs):
        manifest = Path(argv[-1]).read_text()
        assert secret not in json.dumps(argv) + manifest + json.dumps(
            kwargs, default=str
        )
        entry = json.loads(manifest)["sites"][0]
        assert entry["secret_files"]["password"] == str(path)
        seen.append(Path(argv[-1]))
        return subprocess.CompletedProcess(
            argv,
            0 if success else 1,
            json.dumps({"sites": [{"site": "shop", "state": "signed_in"}]})
            if success
            else secret,
            secret,
        )

    monkeypatch.setattr(automatic.subprocess, "run", run)
    if success:
        outcome = automatic.sign_in_expired_sites(None, runtime, "acme", identity())
        assert outcome[0]["state"] == "signed_in"
        assert secret not in json.dumps(outcome)
    else:
        with pytest.raises(automatic.AutomaticSignInError) as error:
            automatic.sign_in_expired_sites(None, runtime, "acme", identity())
        assert "browser_automatic_sign_in_failed" in str(error.value)
        assert "remove sign_in" in str(error.value)
        assert secret not in str(error.value)
    assert not seen[0].exists()
    assert secret not in str(capsys.readouterr())


def test_browser_case_prepares_each_automatic_identity_once(setup, monkeypatch):
    runtime, _, _ = setup
    prepare = Mock(return_value=runtime)
    sign_in = Mock()
    monkeypatch.setattr(
        "yoke_cli.commands.browser_sign_in.prepare_browser_runtime", prepare
    )
    monkeypatch.setattr(automatic, "sign_in_expired_sites", sign_in)
    buyer = identity()
    prepare_automatic_identities(
        "acme", {"buyer": buyer}, ["buyer", "buyer", "default"]
    )
    sign_in.assert_called_once()
    assert sign_in.call_args.args[2:] == ("acme", buyer)


def test_human_identities_need_no_automatic_runtime(monkeypatch):
    prepare = Mock(side_effect=AssertionError("human sign-in must not type"))
    monkeypatch.setattr(
        "yoke_cli.commands.browser_sign_in.prepare_browser_runtime", prepare
    )
    human = declaration()
    del human["sign_in"]
    prepare_automatic_identities("acme", {"buyer": identity(human)}, ["buyer"])
    prepare.assert_not_called()
