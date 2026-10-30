"""Saved authorization is reused independently of installation readiness."""

from __future__ import annotations

from runtime.api.cli.github_user_token_test_support import seed_yoke_connection

import pytest

from yoke_cli.config import github_saved_authorization as saved
from yoke_cli.config import github_app_public_profile as profiles
from yoke_cli.config import github_machine
from runtime.api.cli.test_github_app_machine_connection import (
    _api_opener,
    _device_opener,
    _profile_opener,
)


@pytest.mark.parametrize(
    "verdict,state",
    [("ok", "connected"), ("ok", "pending_installation"), ("busy", "connected")],
)
def test_saved_authorization_does_not_request_another_code(monkeypatch, verdict, state):
    report = {"bindings": {"user_authorization": {"verdict": verdict}}, "state": state}
    calls = []
    monkeypatch.setattr(
        saved.github_machine_status, "status", lambda **kw: calls.append(kw) or report
    )
    result = saved.reuse(
        existing={"authorization": {}},
        metadata={"profile_source": profiles.PROFILE_SOURCE_LOCAL_PRODUCT},
        replace_profile=False,
        config_path="test-config",
    )
    assert result["authorization_reused"] is True
    assert calls[0]["check"] is True
    assert calls[0]["local_connection_selected"] is True


def test_broken_saved_authorization_can_request_fresh_approval(monkeypatch):
    monkeypatch.setattr(
        saved.github_machine_status,
        "status",
        lambda **kw: {"bindings": {"user_authorization": {"verdict": "broken"}}},
    )
    assert (
        saved.reuse(existing={"authorization": {}}, metadata={}, replace_profile=False)
        is None
    )


def test_explicit_replacement_skips_reuse_check(monkeypatch):
    monkeypatch.setattr(
        saved.github_machine_status,
        "status",
        lambda **kw: pytest.fail("replacement checked old authorization"),
    )
    assert (
        saved.reuse(existing={"authorization": {}}, metadata={}, replace_profile=True)
        is None
    )


@pytest.mark.parametrize("installed", [True, False])
def test_second_connect_checks_saved_auth_without_device_flow(
    tmp_path, monkeypatch, installed
):
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    seed_yoke_connection(home / "config.json", service_api_url="https://api.upyoke.com")
    common = dict(
        config_path=home / "config.json",
        service_api_url="https://api.upyoke.com",
        profile_opener=_profile_opener,
        api_opener=_api_opener(installed=installed),
        sleep=lambda _: None,
        monotonic=lambda: 0,
    )
    first = github_machine.connect(**common, device_opener=_device_opener())
    second = github_machine.connect(
        **common,
        device_opener=lambda *a, **k: pytest.fail(
            "saved authorization requested another code"
        ),
    )
    assert first["identity"]["login"] == second["identity"]["login"]
    assert second["authorization_reused"] is True
    assert second["state"] == ("connected" if installed else "pending_installation")
