"""On-demand GitHub binding checks for universes without webhook delivery."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from runtime.api.domain import test_project_github_binding_lifecycle as lifecycle
from runtime.api.domain.test_project_github_binding_lifecycle import (
    _project_owner_actor,
    _verified,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.github_origin import validate_github_api_endpoint
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
    GitHubAppControlPlaneConfig,
)
from yoke_core.domain.github_app_server_installation import (
    ServerVerifiedInstallation,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_github_auth_tokens import (
    bind_local_github_user_token_provider,
)
from yoke_core.domain.project_github_binding import (
    cmd_project_github_binding_status,
    cmd_unbind_project_repo,
)
from yoke_core.domain.project_github_binding_check import (
    ProjectGithubBindingCheckError,
    cmd_check_project_github_binding,
)
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests

API_URL = "https://api.github.com"
binding_db = lifecycle.binding_db


def _server_config(api_url: str = API_URL) -> GitHubAppControlPlaneConfig:
    return GitHubAppControlPlaneConfig(
        issuer="12345",
        private_key_pem="unused-in-tests",
        endpoint=validate_github_api_endpoint(api_url),
        private_key_file="/unused/key.pem",
    )


def _server_installation(status: str = "active") -> ServerVerifiedInstallation:
    verified = _verified()
    return ServerVerifiedInstallation(
        installation_id="77",
        account_id="10",
        account_login="acme",
        account_type="Organization",
        repository_selection="selected",
        permissions=dict(verified.permissions),
        status=status,
    )


class _TokenCache:
    def get_or_mint(self, **kwargs):
        assert kwargs["installation_id"] == 77
        assert kwargs["permissions"] == {"metadata": "read"}
        return SimpleNamespace(token="installation-token")


def test_machine_authorization_reverifies_with_the_bindings_own_ids(
    binding_db,
) -> None:
    seen: dict = {}

    def verifier(**kwargs):
        seen.update(kwargs)
        return replace(_verified(), installation_status="suspended")

    with bind_local_github_user_token_provider(
        lambda: "machine-token", api_url=API_URL
    ):
        result = cmd_check_project_github_binding(
            "externalwebapp",
            user_verifier=verifier,
        )

    assert seen["installation_id"] == "77"
    assert seen["repository_id"] == "88"
    assert seen["expected_github_repo"] == "acme/demo"
    assert seen["expected_api_url"] == API_URL
    assert seen["github_user_access_token"] == "machine-token"
    assert result["installation"]["status"] == "suspended"
    assert result["installation"]["last_verified_at"]


def test_server_app_marks_a_repository_the_installation_no_longer_reaches(
    binding_db,
) -> None:
    def finder(endpoint, path, **kwargs):
        assert path == "/installation/repositories"
        assert kwargs["selected_id"] == 88
        assert kwargs["token"] == "installation-token"
        return None

    result = cmd_check_project_github_binding(
        "externalwebapp",
        control_plane_config=_server_config(),
        server_fetcher=lambda **_kwargs: _server_installation(),
        repository_finder=finder,
        token_cache=_TokenCache(),
    )

    assert result["installation"]["status"] == "active"
    assert result["binding"]["status"] == "unavailable"
    assert result["binding"]["last_error"] == "repository_unavailable"


def test_server_app_skips_the_repository_read_for_a_suspended_installation(
    binding_db,
) -> None:
    def finder(*_args, **_kwargs):
        raise AssertionError("a suspended installation reaches no repository")

    result = cmd_check_project_github_binding(
        "externalwebapp",
        control_plane_config=_server_config(),
        server_fetcher=lambda **_kwargs: _server_installation("suspended"),
        repository_finder=finder,
        token_cache=_TokenCache(),
    )

    assert result["installation"]["status"] == "suspended"
    assert result["automation"]["reason"] == "installation_suspended"


def test_a_server_app_for_another_github_deployment_is_refused(binding_db) -> None:
    with pytest.raises(ProjectGithubBindingCheckError) as refused:
        cmd_check_project_github_binding(
            "externalwebapp",
            control_plane_config=_server_config("https://ghe.example.com/api/v3"),
        )
    assert refused.value.code == "github_check_origin_mismatch"
    assert "github-binding bind" in refused.value.recovery


def test_an_unbound_project_names_the_bind_command(binding_db) -> None:
    cmd_unbind_project_repo("externalwebapp")
    with pytest.raises(ProjectGithubBindingCheckError) as refused:
        cmd_check_project_github_binding("externalwebapp")
    assert refused.value.code == "github_binding_missing"
    assert "yoke projects github-binding bind" in refused.value.recovery


def test_dispatch_without_github_authority_refuses_with_its_recovery(
    binding_db,
    monkeypatch,
) -> None:
    monkeypatch.delenv(GITHUB_APP_ISSUER_ENV, raising=False)
    monkeypatch.delenv(GITHUB_APP_PRIVATE_KEY_FILE_ENV, raising=False)
    reset_registry_for_tests()
    register_all_handlers()
    response = dispatch(
        FunctionCallRequest(
            function="projects.github_binding.check",
            actor=ActorContext(
                actor_id=_project_owner_actor(binding_db, "externalwebapp"),
                session_id="",
            ),
            target=TargetRef(kind="global"),
            request_id="check-without-authority",
            payload={"project": "externalwebapp"},
        ),
        ambient_session_id="",
    )

    assert response.success is False
    assert response.error.code == "github_check_authority_unavailable"
    assert "yoke github connect" in response.error.recovery_hint
    assert "docs/public/self-hosting/install.md" in response.error.recovery_hint


def test_status_names_the_installations_repository_access_page(binding_db) -> None:
    status = cmd_project_github_binding_status("externalwebapp")
    assert status["installation"]["settings_url"] == (
        "https://github.com/organizations/acme/settings/installations/77"
    )
