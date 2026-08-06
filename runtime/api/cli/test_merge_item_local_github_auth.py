"""Local merge carries machine GitHub user authority into its child."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands import merge_item
from yoke_cli.commands import merge_item_local_runtime as local_runtime
from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_core.domain import project_github_auth as project_auth
from yoke_core.domain import project_github_auth_tokens
from yoke_core.domain.github_app_dispatch_context import (
    LOCAL_API_ENDPOINT,
    LOCAL_USER_TOKEN_PROVIDER,
)
from yoke_core.domain.project_github_auth_models import ProjectGithubState


def _state(api_url: str = "https://api.github.com") -> ProjectGithubState:
    return ProjectGithubState(
        project_slug="yoke",
        project_id=1,
        has_capability=True,
        binding={
            "status": "active",
            "github_repo": "upyoke/yoke",
            "installation_id": "12345",
            "repository_id": "4567",
            "api_url": api_url,
        },
        installation={
            "status": "active",
            "permissions": json.dumps(
                dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS)
            ),
            "api_url": api_url,
        },
    )


def _configure_https_machine(monkeypatch, *, api_url: str) -> None:
    monkeypatch.setattr(
        local_runtime.machine_config,
        "github_config",
        lambda: {"api_url": api_url},
    )
    monkeypatch.setattr(
        local_runtime.github_app_public_profile,
        "selected_https_service_api_url",
        lambda: "https://api.stage.upyoke.test",
    )


def test_adapter_launches_authority_binding_child_without_secret_arguments(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(merge_item.subprocess, "run", fake_run)

    assert merge_item.merge_item(["YOK-42", "--skip-status"]) == 7
    assert seen["command"] == [
        merge_item.sys.executable,
        "-m",
        "yoke_cli.commands.merge_item_local_runtime",
        "YOK-42",
        "--skip-status",
    ]
    assert seen["kwargs"] == {"check": False}


def test_https_child_binds_lazy_user_provider_for_entire_merge(
    monkeypatch,
) -> None:
    _configure_https_machine(monkeypatch, api_url="https://api.github.com")
    token_calls: list[dict[str, object]] = []

    def token_loader(**kwargs):
        token_calls.append(kwargs)
        return SimpleNamespace(access_token="transient-user-token")

    monkeypatch.setattr(
        local_runtime.github_local_user_access,
        "access_token",
        token_loader,
    )

    def child_main(argv):
        assert argv == ["YOK-42"]
        endpoint = LOCAL_API_ENDPOINT.get()
        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert endpoint is not None
        assert endpoint.base_url == "https://api.github.com"
        assert provider is not None
        assert token_calls == []
        assert provider() == "transient-user-token"
        return 19

    real_import = local_runtime.importlib.import_module

    def import_module(name: str):
        if name == "yoke_core.domain.standalone_item_merge_cli":
            return SimpleNamespace(main=child_main)
        return real_import(name)

    monkeypatch.setattr(local_runtime.importlib, "import_module", import_module)

    assert local_runtime.run(["YOK-42"]) == 19
    assert token_calls == [
        {
            "service_api_url": "https://api.stage.upyoke.test",
            "local_connection_selected": False,
        }
    ]
    assert LOCAL_API_ENDPOINT.get() is None
    assert LOCAL_USER_TOKEN_PROVIDER.get() is None


def test_bound_user_provider_never_reads_service_app_credentials(
    monkeypatch,
) -> None:
    _configure_https_machine(monkeypatch, api_url="https://api.github.com")
    monkeypatch.setattr(
        local_runtime.github_local_user_access,
        "access_token",
        lambda **_kwargs: SimpleNamespace(access_token="transient-user-token"),
    )
    monkeypatch.setattr(
        project_auth, "read_github_state", lambda *_args, **_kw: _state()
    )
    monkeypatch.setattr(
        project_github_auth_tokens,
        "load_github_app_control_plane_config",
        lambda: pytest.fail("local merge must not read service App credentials"),
    )

    with local_runtime.machine_github_user_authority():
        resolved = project_auth.resolve_project_github_auth("yoke")

    assert resolved.token == "transient-user-token"
    assert resolved.token_source == "github_app_user"


def test_origin_mismatch_fails_before_token_or_service_credential_lookup(
    monkeypatch,
) -> None:
    _configure_https_machine(
        monkeypatch,
        api_url="https://github.enterprise.test/api/v3",
    )
    monkeypatch.setattr(
        local_runtime.github_local_user_access,
        "access_token",
        lambda **_kwargs: pytest.fail("origin mismatch must precede token refresh"),
    )
    monkeypatch.setattr(
        project_auth, "read_github_state", lambda *_args, **_kw: _state()
    )
    monkeypatch.setattr(
        project_github_auth_tokens,
        "load_github_app_control_plane_config",
        lambda: pytest.fail("origin mismatch must not read service credentials"),
    )

    with local_runtime.machine_github_user_authority():
        with pytest.raises(
            project_auth.UserAuthorizationUnavailable,
            match="reconnect using the matching GitHub deployment",
        ):
            project_auth.resolve_project_github_auth("yoke")


def test_missing_machine_authorization_teaches_reconnect_without_service_key(
    monkeypatch,
) -> None:
    _configure_https_machine(monkeypatch, api_url="https://api.github.com")
    monkeypatch.setattr(local_runtime.machine_config, "github_config", lambda: {})
    monkeypatch.setattr(
        project_auth, "read_github_state", lambda *_args, **_kw: _state()
    )
    monkeypatch.setattr(
        project_github_auth_tokens,
        "load_github_app_control_plane_config",
        lambda: pytest.fail("missing local auth must not read service credentials"),
    )

    with local_runtime.machine_github_user_authority():
        with pytest.raises(project_auth.UserAuthorizationUnavailable) as info:
            project_auth.resolve_project_github_auth("yoke")

    message = str(info.value)
    assert "reconnect GitHub on this machine" in message
    assert "private-key" not in message
