"""Selected HTTPS service GitHub App profile isolation."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.cli.test_github_app_public_profile import _Response, _advertisement
from yoke_cli.config import (
    github_app_public_profile,
    github_binding_auth,
    github_machine,
    github_service_profile_proof,
)
from yoke_contracts import github_app_public
from yoke_contracts.machine_config import schema as machine_contract


def test_https_binding_ignores_hostile_matching_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = {
        key: value for key, value in _advertisement().items() if key != "available"
    }
    saved.update(
        {
            "profile_source": "service",
            "profile_service_api_url": "https://foreign.example",
        }
    )
    for field, env_name in (
        ("client_id", github_app_public.GITHUB_APP_CLIENT_ID_ENV),
        ("app_slug", github_app_public.GITHUB_APP_SLUG_ENV),
        ("app_id", github_app_public.GITHUB_APP_ID_ENV),
        ("api_url", github_app_public.GITHUB_APP_API_URL_ENV),
        ("web_url", github_app_public.GITHUB_APP_WEB_URL_ENV),
    ):
        monkeypatch.setenv(env_name, str(saved[field]))
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda _path=None: saved,
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "active_connection",
        lambda _path=None: {
            "transport": "https",
            "api_url": "https://foreign.example",
        },
    )
    token_calls: list[str] = []
    monkeypatch.setattr(
        github_binding_auth.github_user_tokens,
        "access_token_from_machine_config",
        lambda **kwargs: token_calls.append("token"),
    )

    with pytest.raises(
        github_binding_auth.GitHubBindingAuthError,
        match="unavailable",
    ):
        github_binding_auth.access_token_for_binding(
            profile_opener=lambda request, timeout: _Response(
                {"github_app": {"available": False}}, url=request.full_url
            ),
        )

    assert token_calls == []


def test_selected_service_connect_ignores_complete_environment_override(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field, env_name in (
        ("client_id", github_app_public.GITHUB_APP_CLIENT_ID_ENV),
        ("app_slug", github_app_public.GITHUB_APP_SLUG_ENV),
        ("app_id", github_app_public.GITHUB_APP_ID_ENV),
        ("api_url", github_app_public.GITHUB_APP_API_URL_ENV),
        ("web_url", github_app_public.GITHUB_APP_WEB_URL_ENV),
    ):
        monkeypatch.setenv(env_name, str(_advertisement()[field]))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    device_calls: list[str] = []

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="unavailable",
    ):
        github_machine.connect(
            config_path=tmp_path / "home" / "config.json",
            service_api_url="https://foreign.example",
            profile_opener=lambda request, timeout: _Response(
                {"github_app": {"available": False}}, url=request.full_url
            ),
            device_opener=lambda request, timeout: device_calls.append(
                request.full_url
            ),
        )

    assert device_calls == []


def test_selected_service_failure_never_defaults_to_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        github_app_public_profile.machine_config,
        "active_connection",
        lambda _path=None: (_ for _ in ()).throw(
            machine_contract.MachineConfigContractError("dangling env")
        ),
    )

    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="unavailable or invalid",
    ):
        github_app_public_profile.selected_https_service_api_url()


def test_selected_service_distinguishes_explicit_local_and_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = {"transport": "local-postgres"}
    monkeypatch.setattr(
        github_app_public_profile.machine_config,
        "active_connection",
        lambda _path=None: selected,
    )
    assert github_app_public_profile.selected_https_service_api_url() is None

    selected.update(
        {
            "transport": "https",
            "api_url": "https://stage.yoke.example/",
        }
    )
    assert github_app_public_profile.selected_https_service_api_url() == (
        "https://stage.yoke.example"
    )


def test_explicit_local_scope_ignores_active_hosted_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    saved["profile_source"] = "local_explicit"
    monkeypatch.setattr(
        github_app_public_profile.machine_config,
        "active_connection",
        lambda _path=None: {
            "transport": "https",
            "api_url": "https://api.upyoke.com",
        },
    )

    resolved = github_app_public_profile.resolve_selected_and_match(
        saved,
        config_path="/tmp/config.json",
        local_connection_selected=True,
    )

    assert resolved.client_id == saved["client_id"]
    assert github_service_profile_proof.selected_service_api_url(
        {
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "api_url": "https://api.upyoke.com",
                },
            },
        },
        saved,
        expected_local_connection=True,
    ) is None


@pytest.mark.parametrize(
    ("service_api_url", "local_connection_selected"),
    (
        (None, True),
        ("https://stage.yoke.example", False),
    ),
)
def test_binding_authority_preserves_explicit_connection_scope(
    monkeypatch: pytest.MonkeyPatch,
    service_api_url: str | None,
    local_connection_selected: bool,
) -> None:
    saved = {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    seen: dict[str, dict[str, Any]] = {}

    @contextmanager
    def unlocked(_path):
        yield

    def resolve_profile(_github, **kwargs):
        seen["profile"] = kwargs
        return SimpleNamespace(**saved)

    def resolve_token(**kwargs):
        seen["token"] = kwargs
        return SimpleNamespace(access_token="transient-user-token")

    monkeypatch.setattr(
        github_binding_auth.github_machine_operation,
        "operation_lock",
        unlocked,
    )
    monkeypatch.setattr(
        github_binding_auth.machine_config,
        "github_config",
        lambda _path=None: saved,
    )
    monkeypatch.setattr(
        github_binding_auth.github_app_public_profile,
        "resolve_selected_and_match",
        resolve_profile,
    )
    monkeypatch.setattr(
        github_binding_auth.github_user_tokens,
        "access_token_from_machine_config",
        resolve_token,
    )

    with github_binding_auth.locked_profile_bound_access_for_binding(
        "/tmp/config.json",
        service_api_url=service_api_url,
        local_connection_selected=local_connection_selected,
    ) as authority:
        assert authority.token.access_token == "transient-user-token"

    assert seen["profile"]["service_api_url"] == service_api_url
    assert seen["profile"]["local_connection_selected"] is (
        local_connection_selected
    )
    assert seen["token"]["_expected_service_api_url"] == service_api_url
    assert seen["token"]["_expected_local_connection"] is (
        local_connection_selected
    )


def test_non_https_service_scope_fails_before_profile_fetch() -> None:
    saved = {
        key: value for key, value in _advertisement().items()
        if key != "available"
    }
    saved.update({
        "profile_source": "service",
        "profile_service_api_url": "https://api.upyoke.com",
    })
    profile_calls: list[str] = []

    with pytest.raises(
        github_app_public_profile.GitHubAppPublicProfileError,
        match="credential-free HTTPS",
    ):
        github_app_public_profile.resolve_selected_and_match(
            saved,
            config_path="/tmp/config.json",
            service_api_url="http://127.0.0.1:9444",
            opener=lambda request, timeout: profile_calls.append(request.full_url),
        )

    assert profile_calls == []


def test_plain_local_connect_ignores_complete_profile_environment(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field, env_name in (
        ("client_id", github_app_public.GITHUB_APP_CLIENT_ID_ENV),
        ("app_slug", github_app_public.GITHUB_APP_SLUG_ENV),
        ("app_id", github_app_public.GITHUB_APP_ID_ENV),
        ("api_url", github_app_public.GITHUB_APP_API_URL_ENV),
        ("web_url", github_app_public.GITHUB_APP_WEB_URL_ENV),
    ):
        monkeypatch.setenv(env_name, str(_advertisement()[field]))
    monkeypatch.setattr(
        github_machine.github_machine_profile.github_app_public_profile,
        "selected_https_service_api_url",
        lambda _path=None: None,
    )
    bundled = github_app_public_profile.bundled_local_product_profile()
    seen: dict[str, Any] = {}

    def stop_after_profile(**kwargs):
        seen.update(kwargs)
        raise github_machine.github_device_flow.GitHubDeviceFlowError("stop")

    monkeypatch.setattr(
        github_machine.github_device_flow,
        "authorize",
        stop_after_profile,
    )

    with pytest.raises(
        github_machine.GitHubMachineError,
        match="stop",
    ):
        github_machine.connect(config_path=tmp_path / "config.json")

    assert seen["client_id"] == bundled.client_id
    assert seen["web_url"] == bundled.web_url
