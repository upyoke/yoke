"""Installation-authorized merges tolerate unavailable machine user tokens."""

from __future__ import annotations

import json
from types import SimpleNamespace
import pytest
from yoke_contracts.github_app_installation_permissions import (
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)
from yoke_core.domain import project_github_auth as project_auth
from yoke_core.domain.project_github_auth_models import (
    GITHUB_AUTHORITY_INSTALLATION,
    GITHUB_AUTHORITY_USER,
    ProjectGithubState,
    UserAuthorizationUnavailable,
)


def _healthy_state() -> ProjectGithubState:
    api_url = "https://api.github.com"
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


class TestResolverHonorsTheClassification:
    """An installation-authorized read is not refused for want of a user token."""

    @pytest.fixture(autouse=True)
    def _healthy_binding(self, monkeypatch):
        monkeypatch.setattr(
            project_auth,
            "read_github_state",
            lambda *_a, **_k: _healthy_state(),
        )
        monkeypatch.setattr(
            project_auth,
            "register_installation_token",
            lambda *_a, **_k: None,
        )

    def _refuse_user_authorization(self, monkeypatch) -> None:
        def _unavailable(state, **_kwargs):
            raise UserAuthorizationUnavailable(
                state.project_slug,
                "local GitHub App user authorization is unavailable; "
                "reconnect GitHub on this machine",
            )

        monkeypatch.setattr(project_auth, "resolve_local_user_token", _unavailable)

    def _installation_token(self, monkeypatch, token: str = "ghs_installation") -> None:
        monkeypatch.setattr(
            project_auth,
            "read_app_credentials",
            lambda *_a, **_k: SimpleNamespace(
                issuer="1",
                private_key_pem="k",
                api_url="https://api.github.com",
                private_key_file="/k.pem",
            ),
        )
        monkeypatch.setattr(
            project_auth,
            "mint_bound_installation_token",
            lambda *_a, **_k: SimpleNamespace(
                token=token,
                expires_at=SimpleNamespace(isoformat=lambda: "later"),
            ),
        )

    def test_installation_authority_stands_in_for_an_unavailable_user_token(
        self,
        monkeypatch,
    ) -> None:
        self._refuse_user_authorization(monkeypatch)
        self._installation_token(monkeypatch)

        resolved = project_auth.resolve_project_github_auth(
            "yoke",
            required_authority=GITHUB_AUTHORITY_INSTALLATION,
        )

        assert resolved.token == "ghs_installation"
        assert resolved.token_source == GITHUB_AUTHORITY_INSTALLATION

    def test_user_authority_never_falls_back_to_the_installation(
        self,
        monkeypatch,
    ) -> None:
        self._refuse_user_authorization(monkeypatch)
        monkeypatch.setattr(
            project_auth,
            "read_app_credentials",
            lambda *_a, **_k: pytest.fail(
                "a user-authorized operation must not mint an installation token"
            ),
        )

        with pytest.raises(UserAuthorizationUnavailable, match="reconnect GitHub"):
            project_auth.resolve_project_github_auth(
                "yoke",
                required_authority=GITHUB_AUTHORITY_USER,
            )

    def test_reconnect_outranks_a_missing_service_key_when_neither_works(
        self,
        monkeypatch,
    ) -> None:
        self._refuse_user_authorization(monkeypatch)

        def _no_credentials(*_a, **_k):
            raise project_auth.MissingAppCredentials(
                "yoke",
                "GitHub App control-plane credentials are unavailable",
            )

        monkeypatch.setattr(project_auth, "read_app_credentials", _no_credentials)

        with pytest.raises(UserAuthorizationUnavailable, match="reconnect GitHub"):
            project_auth.resolve_project_github_auth(
                "yoke",
                required_authority=GITHUB_AUTHORITY_INSTALLATION,
            )
