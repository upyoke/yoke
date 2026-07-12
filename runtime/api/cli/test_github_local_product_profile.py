"""Bundled local-product GitHub App profile selection and provenance."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.cli.test_github_app_public_profile import (
    _advertisement,
    _bundled_profile,
)
from yoke_cli.config import (
    github_app_public_profile,
    github_binding_auth,
    github_machine,
)
from yoke_contracts import github_app_public
from yoke_contracts.machine_config import schema as machine_contract


def test_bundled_local_product_profile_is_typed_and_environment_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = _advertisement(
        client_id="Iv1.hostile",
        app_slug="hostile",
        app_id=999,
    )
    for field, env_name in (
        ("client_id", github_app_public.GITHUB_APP_CLIENT_ID_ENV),
        ("app_slug", github_app_public.GITHUB_APP_SLUG_ENV),
        ("app_id", github_app_public.GITHUB_APP_ID_ENV),
        ("api_url", github_app_public.GITHUB_APP_API_URL_ENV),
        ("web_url", github_app_public.GITHUB_APP_WEB_URL_ENV),
    ):
        monkeypatch.setenv(env_name, str(hostile[field]))
    bundled = {
        key: value for key, value in _advertisement().items() if key != "available"
    }
    monkeypatch.setattr(
        github_app_public_profile.github_app_tokens,
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE",
        _bundled_profile(bundled),
    )

    profile = github_app_public_profile.bundled_local_product_profile()
    metadata = github_app_public_profile.local_product_metadata()

    assert isinstance(profile, github_app_public.GitHubAppPublicProfile)
    assert tuple(
        github_app_public_profile.github_app_tokens.LocalProductGitHubAppProfile._fields
    ) == ("client_id", "app_slug", "app_id", "api_url", "web_url")
    assert not any(
        "secret" in field or "private" in field
        for field in (
            github_app_public_profile.github_app_tokens.LocalProductGitHubAppProfile._fields
        )
    )
    assert github_app_public_profile.as_metadata(profile) == bundled
    assert metadata == {
        **bundled,
        "profile_source": machine_contract.GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT,
    }


def test_bundled_local_product_profile_is_fail_closed_until_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_app_public_profile.github_app_tokens,
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE",
        None,
    )

    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="unavailable in this Yoke release",
    ):
        github_app_public_profile.bundled_local_product_profile()


def test_local_product_saved_profile_must_match_current_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = {
        key: value for key, value in _advertisement().items() if key != "available"
    }
    monkeypatch.setattr(
        github_app_public_profile.github_app_tokens,
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE",
        _bundled_profile(bundled),
    )
    monkeypatch.setattr(
        github_app_public_profile.machine_config,
        "active_connection",
        lambda _path=None: {"transport": "local-postgres", "env": "local"},
    )
    saved = {**bundled, "profile_source": "local_product"}

    assert (
        github_app_public_profile.resolve_selected_and_match(
            saved,
            config_path="/tmp/config.json",
        ).client_id
        == bundled["client_id"]
    )
    saved["app_id"] = 999
    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="different Yoke GitHub App profile",
    ):
        github_app_public_profile.resolve_selected_and_match(
            saved,
            config_path="/tmp/config.json",
        )


def test_machine_connect_selects_bundled_profile_for_local_transport(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = {
        key: value for key, value in _advertisement().items() if key != "available"
    }
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        github_app_public_profile.github_app_tokens,
        "BUNDLED_LOCAL_PRODUCT_GITHUB_APP_PROFILE",
        _bundled_profile(bundled),
    )
    monkeypatch.setattr(
        github_machine.github_machine_profile.github_app_public_profile,
        "selected_https_service_api_url",
        lambda _path=None: None,
    )
    seen: dict[str, Any] = {}

    def stop_after_profile(**kwargs):
        seen.update(kwargs)
        raise github_machine.github_device_flow.GitHubDeviceFlowError("stop")

    monkeypatch.setattr(
        github_machine.github_device_flow,
        "authorize",
        stop_after_profile,
    )

    with pytest.raises(github_machine.GitHubMachineError, match="stop"):
        github_machine.connect(config_path=tmp_path / "home" / "config.json")

    assert seen["client_id"] == bundled["client_id"]
    assert seen["web_url"] == bundled["web_url"]


def test_machine_contract_types_local_product_provenance() -> None:
    github = {
        **{key: value for key, value in _advertisement().items() if key != "available"},
        "profile_source": "local_product",
        "authorization": {
            "kind": machine_contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": "/tmp/github-refresh.json",
            "status": "authorized",
        },
    }

    assert machine_contract.validate_github_config({"github": github}) == []
    github["profile_service_api_url"] = "https://api.upyoke.com"
    assert [
        issue.code
        for issue in machine_contract.validate_github_config({"github": github})
    ] == ["github_profile_service_unexpected"]


def test_binding_auth_wraps_invalid_machine_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda _path=None: (_ for _ in ()).throw(
            github_binding_auth.machine_config.MachineConfigError(
                "invalid machine config"
            )
        ),
    )

    with pytest.raises(
        github_binding_auth.GitHubBindingAuthError,
        match="invalid machine config",
    ):
        github_binding_auth.profile_bound_access_for_binding()
