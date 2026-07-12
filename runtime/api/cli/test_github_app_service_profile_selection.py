"""Selected HTTPS service GitHub App profile isolation."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.cli.test_github_app_public_profile import _Response, _advertisement
from yoke_cli.config import (
    github_app_public_profile,
    github_binding_auth,
    github_machine,
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
