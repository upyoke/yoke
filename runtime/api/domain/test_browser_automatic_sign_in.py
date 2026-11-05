"""Credential isolation and automatic Browser case preparation."""

from runtime.api.domain.browser_automatic_sign_in_test_support import (
    declaration as declaration,
    identity as identity,
)


import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.browser_identity import (
    BrowserIdentityError,
)
from yoke_contracts.machine_config.capability_secrets import (
    is_machine_local_capability_secret,
)
from yoke_cli.config.capability_secrets import (
    list_machine_capability_secret_keys,
    store_machine_capability_secret,
)
from yoke_harness import browser_automatic_sign_in as automatic


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
    "origins",
    [
        ["https://*.identity.example"],
        ["https://identity.example/login"],
        ["http://identity.example"],
        ["https://user@identity.example"],
        ["https://identity.example", "https://identity.example"],
        ["https://identity.example", "https://IDENTITY.example:443"],
        ["https://identity.example?"],
        ["https://identity.example#"],
        ["https://identity.example/"],
        ["https://identity.example:bad"],
        ["https://"],
        [None],
        "https://identity.example",
    ],
)
def test_parser_rejects_unsafe_credential_origins(origins):
    site = declaration()
    site["sign_in"]["credential_origins"] = origins
    with pytest.raises(BrowserIdentityError, match="credential_origins"):
        identity(site)


def test_parser_keeps_exact_credential_origins():
    assert identity().sites[0].sign_in.credential_origins == ()
    site = declaration()
    origins = ["https://identity.example", "https://identity.example:8443"]
    site["sign_in"]["credential_origins"] = origins
    assert identity(site).sites[0].sign_in.credential_origins == tuple(origins)


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


def test_runtime_unreadable_secret_teaches_its_exact_setup_command(setup, monkeypatch):
    runtime, _, _ = setup
    store_machine_capability_secret(
        "acme", "browser-control", "sign-in.buyer.shop.password", "synthetic"
    )
    monkeypatch.setattr(
        automatic.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "sites": [
                        {"site": "shop", "state": "secret_missing", "field": "password"}
                    ]
                }
            ),
            "",
        ),
    )
    with pytest.raises(
        automatic.AutomaticSignInError,
        match="browser_sign_in_secret_missing:.*--key sign-in.buyer.shop.password --value-stdin",
    ):
        automatic.sign_in_expired_sites(None, runtime, "acme", identity())


def test_scenario_copies_sign_in_without_refreshing_authoritative_profile(monkeypatch):
    from yoke_core.domain import browser_qa
    from yoke_core.domain import browser_qa_scenario as scenario

    events = []
    context = {
        "standalone_execution_id": "fixture",
        "requirements": [
            {
                "id": 1,
                "method_config": json.dumps({"browser_identity": "buyer"}),
            }
        ],
    }
    monkeypatch.setattr(browser_qa, "_fetch_browser_context", lambda *a, **k: context)
    monkeypatch.setattr(browser_qa, "_validate_reachability", lambda *a: None)
    monkeypatch.setattr(
        browser_qa, "load_project_browser_identities", lambda *a: {"buyer": identity()}
    )

    def daemon(**kwargs):
        events.append("daemon")

    def process(**kwargs):
        events.append("step")
        return SimpleNamespace(
            run_result=SimpleNamespace(verdict="pass"),
            skipped=False,
            executed=True,
            capture_failed=False,
            env_failure=False,
        )

    sign_in = Mock(side_effect=AssertionError("QA must not refresh the main profile"))
    monkeypatch.setattr(automatic, "sign_in_expired_sites", sign_in)
    monkeypatch.setattr(browser_qa, "_ensure_daemon_running", daemon)
    monkeypatch.setattr(scenario, "_process_requirement", process)
    result = scenario.execute_scenario("acme", 1, base_url="https://shop.example")
    assert events == ["daemon", "step"]
    assert result.verdict == "pass"
    sign_in.assert_not_called()
