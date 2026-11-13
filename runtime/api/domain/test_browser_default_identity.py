"""default_identity, any-endpoint identity offers, and check-id inheritance."""

import json
import os
from types import SimpleNamespace

import pytest

from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    declared_default_identity,
    parse_identity_declarations,
    select_declared_identity,
    select_identity,
)
from yoke_core.domain.agent_mission_brief import _walker_dispatch
from yoke_core.domain.agent_mission_browser_identities import walker_identity_dispatch
from yoke_core.domain.browser_qa_sign_in_evidence import resolve_case_identities
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)

APP = "https://app.upyoke.com"


def _site(origin):
    return {"site": "app", "origin": origin, "probe": {"url": origin + "/me", "signed_in_status": 200}}


def _settings(default_identity=None):
    settings = {
        "identities": {
            "admin": {"sites": [_site(APP)]},
            "operator": {"sites": [_site(APP)]},
            "other": {"sites": [_site("https://elsewhere.example")]},
        }
    }
    if default_identity is not None:
        settings["default_identity"] = default_identity
    return settings


HOSTED_TARGET = {
    "endpoints": {"app_url": APP + "/dashboard", "api_url": "https://api.upyoke.com"}
}


def test_a_hosted_target_without_base_url_offers_identities_for_any_url_endpoint():
    identities, commands, clause, preferred = walker_identity_dispatch(
        {"method_config": {}},
        None,
        browser_settings=_settings(),
        execution_target=HOSTED_TARGET,
    )
    assert identities == ["admin", "operator"]
    assert [c.split("--identity ")[1].split()[0] for c in commands] == identities
    assert preferred is None and "account fits the case" in clause


def test_non_url_endpoint_keys_are_ignored():
    identities, *_ = walker_identity_dispatch(
        {"method_config": {}},
        None,
        browser_settings=_settings(),
        execution_target={"endpoints": {"app_host": APP, "region": "us"}},
    )
    assert identities == []


def test_settings_write_refuses_a_default_identity_naming_no_declared_identity():
    with pytest.raises(BrowserIdentityError, match="^browser_identity_undeclared:"):
        canonicalize_capability_settings(
            "browser-control", json.dumps(_settings("nobody"))
        )
    stored = canonicalize_capability_settings(
        "browser-control", json.dumps(_settings("operator"))
    )
    assert json.loads(stored)["default_identity"] == "operator"
    assert declared_default_identity(_settings("default")) == "default"
    assert declared_default_identity(_settings()) is None


def test_omitted_identity_uses_default_identity_and_explicit_names_win():
    assert select_declared_identity(_settings("operator"), None).name == "operator"
    assert select_declared_identity(_settings("operator"), "admin").name == "admin"
    assert select_declared_identity(_settings("operator"), "default").name == "default"
    declared = parse_identity_declarations(_settings())
    assert select_identity(declared, None, "admin").name == "admin"
    with pytest.raises(BrowserIdentityError, match="browser_identity_required"):
        select_declared_identity(_settings(), None)


def test_project_without_default_identity_keeps_its_behaviour():
    assert select_declared_identity({}, None).name == "default"
    sited_default = {"identities": {"default": {"sites": [_site(APP)]}}}
    assert select_declared_identity(sited_default, None).name == "default"


def test_case_omission_stays_anonymous_default_even_with_default_identity():
    declared = parse_identity_declarations(_settings("operator"))
    assert resolve_case_identities(declared, [{"method_config": "{}"}]) == ["default"]


def _case(**config):
    return {
        "requirement_id": 1,
        "capture_run_id": 2,
        "executor": "informed_subagent",
        "instructions": "Explore",
        "expected_outcome": "Findings",
        "method_config": config,
    }


def test_controller_brief_lists_default_identity_first_and_passes_it():
    brief = _walker_dispatch(
        _case(),
        execution_id="walk",
        subject_flag="--project example",
        browser_settings=_settings("operator"),
        execution_target=HOSTED_TARGET,
    )
    assert brief["browser_identities"] == ["operator", "admin"]
    assert "--identity operator" in brief["browser_setup_command"]
    assert "--identity operator" in brief["browser_step_command"]
    assert "unless the case needs another account" in brief["prompt"]


def test_host_brief_passes_default_identity_on_setup_and_step():
    brief = _walker_dispatch(
        _case(test_machine="test-mac"),
        execution_id="walk",
        subject_flag="--project example",
        browser_settings=_settings("operator"),
        execution_target=HOSTED_TARGET,
    )
    assert brief["browser_identities"][0] == "operator"
    assert brief["browser_setup_command"].endswith("--identity operator")
    assert "--identity operator [--page NAME]" in brief["browser_step_command"]


def test_mission_identity_list_wins_over_default_identity():
    brief = _walker_dispatch(
        _case(browser_identities=["admin"]),
        execution_id="walk",
        subject_flag="--project example",
        browser_settings=_settings("operator"),
        execution_target=HOSTED_TARGET,
    )
    assert brief["browser_identities"] == ["admin"]
    assert "[--identity NAME]" in brief["browser_setup_command"]


def test_default_identity_not_offered_is_not_preferred():
    identities, _, _, preferred = walker_identity_dispatch(
        {"method_config": {}},
        None,
        browser_settings=_settings("other"),
        execution_target=HOSTED_TARGET,
    )
    assert identities == ["admin", "operator"] and preferred is None


def test_bare_setup_reads_no_declarations_and_opens_default():
    from yoke_cli.commands.qa_browser_lifecycle import _declared_identity

    assert _declared_identity("acme", None) == "default"


def test_check_id_without_identity_inherits_the_checks_identity(tmp_path, monkeypatch):
    from yoke_harness import browser_check_profile as checks
    from yoke_harness import browser_client

    source = tmp_path / "authoritative"
    source.mkdir()
    (source / "Cookies").write_bytes(b"sign-in")
    monkeypatch.setattr(checks.machine_config, "yoke_home", lambda: tmp_path / "m")
    monkeypatch.setattr(
        checks, "resolve_authorized_profile", lambda *a, **k: (source, "authorized")
    )
    monkeypatch.setattr(checks, "keep_sign_in_cookies", lambda profile: 0)
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: tmp_path / "runtime")
    monkeypatch.setattr(browser_client, "daemon_stop", lambda **kw: None)
    monkeypatch.setattr(
        browser_client.DaemonState, "load", lambda *a: SimpleNamespace(pid=os.getpid())
    )
    monkeypatch.setattr(browser_client, "daemon_running", lambda state: True)
    with checks.check_scope("fixture", "admin", keep_open=True) as started:
        assert started.identity == "admin"
    with checks.check_scope("fixture", check_id=started.check_id, keep_open=True) as step:
        assert step.identity == "admin" and step.profile == started.profile
    with pytest.raises(RuntimeError, match="browser_check_identity_mismatch"):
        with checks.check_scope("fixture", "default", check_id=started.check_id):
            pytest.fail("an explicit different identity must refuse")
    with checks.check_scope("fixture", check_id=started.check_id):
        pass
    assert not started.directory.exists()
