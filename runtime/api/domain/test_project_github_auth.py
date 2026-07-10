# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
    GITHUB_METADATA_READ_PERMISSION_LEVELS,
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)

from runtime.api.domain.project_github_auth_test_support import (
    _bind_yoke,
    _init_with_projects,
    _minted,
    _p,
    app_bound_db as app_bound_db,
    control_plane_config as control_plane_config,
    db_path as db_path,
)
from yoke_core.domain import (
    project_github_auth as pga, project_github_auth_tokens,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.github_app_token_models import GitHubAppTokenError
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfigError
from yoke_core.domain.project_github_auth_models import (
    AppCredentials,
    ProjectGithubState,
)
from yoke_core.domain.project_github_auth_tokens import (
    mint_bound_installation_token,
)


class TestHappyPath:
    def test_resolves_installation_token(self, app_bound_db: str):
        seen: dict[str, Any] = {}

        def fake_minter(**kwargs):
            seen.update(kwargs)
            return _minted()

        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            token_minter=fake_minter,
        )

        assert isinstance(result, pga.ProjectGithubAuth)
        assert result.project == "yoke"
        assert result.repo == "upyoke/yoke"
        assert result.token == "ghs_install"
        assert not hasattr(result, "env")
        assert result.installation_id == "12345"
        assert result.token_source == "github_app_installation"
        assert result.token_expires_at == "2026-07-09T18:00:00+00:00"
        assert "ghs_install" not in repr(result)
        assert seen["issuer"] == "Iv1.local"
        assert seen["private_key_pem"] == "test-private-key"
        assert seen["installation_id"] == "12345"
        assert seen["repository_ids"] == [4567]
        assert seen["permissions"] == dict(
            GITHUB_METADATA_READ_PERMISSION_LEVELS
        )

    def test_rejects_binding_without_verified_repository_id(self, db_path: str):
        state = ProjectGithubState(
            project_slug="yoke",
            project_id=1,
            has_capability=True,
            binding={"installation_id": "12345", "repository_id": None},
            installation={},
        )
        credentials = AppCredentials(
            issuer="Iv1.local",
            private_key_pem="test-private-key",
            api_url="https://api.github.com",
            private_key_file="/run/secrets/yoke-github-app-key",
        )
        assert "test-private-key" not in repr(credentials)
        with pytest.raises(pga.MissingRepoMetadata, match="repository id"):
            mint_bound_installation_token(
                state,
                credentials=credentials,
                token_permissions=dict(
                    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
                ),
                token_cache=None,
                token_minter=lambda **_kwargs: pytest.fail(
                    "invalid bindings must fail before token minting"
                ),
            )

    def test_returns_frozen_bundle(self, app_bound_db: str):
        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            token_minter=lambda **_kwargs: _minted(),
        )
        with pytest.raises(Exception):
            result.token = "tampered"  # type: ignore[misc]

    def test_optional_permission_is_checked_and_added_to_installation_token(
        self, db_path: str,
    ):
        _init_with_projects(db_path)
        permissions = dict(REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS)
        permissions["administration"] = "read"
        _bind_yoke(db_path, permissions=permissions)
        seen: dict[str, Any] = {}

        def fake_minter(**kwargs):
            seen.update(kwargs)
            return _minted()

        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=db_path,
            token_minter=fake_minter,
            required_permissions=GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
        )

        assert result.permissions["administration"] == "read"
        assert seen["permissions"] == {
            "administration": "read",
            "metadata": "read",
        }

    def test_optional_permission_does_not_replace_full_contract_validation(
        self, db_path: str,
    ):
        _init_with_projects(db_path)
        _bind_yoke(db_path)

        with pytest.raises(pga.MissingPermission, match="administration"):
            pga.resolve_project_github_auth(
                "yoke",
                db_path=db_path,
                token_minter=lambda **_kwargs: pytest.fail(
                    "missing installation permissions must fail before minting"
                ),
                required_permissions=GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
            )


class TestFailureModes:
    def test_missing_capability(self, db_path: str):
        _init_with_projects(db_path)

        with pytest.raises(pga.MissingCapability) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path)
        assert info.value.code == "missing_capability"
        assert info.value.project == "yoke"

    def test_missing_repo_binding_with_capability(self, db_path: str):
        _init_with_projects(db_path)
        _bind_yoke(db_path)
        conn = connect(db_path)
        try:
            conn.execute("DELETE FROM project_github_repo_bindings")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(pga.MissingRepoBinding) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path)
        assert info.value.code == "missing_repo_binding"

    def test_missing_repo_metadata(self, app_bound_db: str):
        conn = connect(app_bound_db)
        try:
            conn.execute(
                f"UPDATE project_github_repo_bindings SET github_repo={_p(conn)} "
                f"WHERE project_id={_p(conn)}",
                ("", 1),
            )
            conn.execute(
                f"UPDATE projects SET github_repo={_p(conn)} WHERE id={_p(conn)}",
                ("legacy-owner/legacy-repo", 1),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(pga.MissingRepoMetadata) as info:
            pga.resolve_project_github_auth("yoke", db_path=app_bound_db)
        assert info.value.code == "missing_repo_metadata"
        assert "legacy-owner/legacy-repo" not in str(info.value)

    def test_missing_installation(self, app_bound_db: str):
        conn = connect(app_bound_db)
        try:
            # Model a pre-convergence orphan. Current schema prevents this state
            # with an FK, while the resolver still fails closed if legacy drift
            # is encountered before convergence repairs it.
            conn.execute(
                "ALTER TABLE project_github_repo_bindings DROP CONSTRAINT "
                "project_github_repo_bindings_installation_id_fkey"
            )
            conn.execute(
                f"DELETE FROM github_app_installations WHERE installation_id={_p(conn)}",
                ("12345",),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(pga.MissingInstallation) as info:
            pga.resolve_project_github_auth("yoke", db_path=app_bound_db)
        assert info.value.code == "missing_installation"

    def test_binding_unavailable(self, db_path: str):
        _init_with_projects(db_path)
        _bind_yoke(db_path, binding_status="unavailable")

        with pytest.raises(pga.BindingUnavailable) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path)
        assert info.value.code == "binding_unavailable"

    def test_installation_unavailable(self, db_path: str):
        _init_with_projects(db_path)
        _bind_yoke(db_path, installation_status="suspended")

        with pytest.raises(pga.InstallationUnavailable) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path)
        assert info.value.code == "installation_unavailable"

    def test_missing_permission(self, db_path: str):
        _init_with_projects(db_path)
        _bind_yoke(db_path, permissions={"metadata": "read", "issues": "read"})

        with pytest.raises(pga.MissingPermission) as info:
            pga.resolve_project_github_auth(
                "yoke",
                db_path=db_path,
                token_minter=lambda **_kwargs: pytest.fail(
                    "the full App contract must fail before token minting"
                ),
            )
        assert info.value.code == "missing_permission"
        assert "issues" in str(info.value)

    def test_missing_app_credentials(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch,
    ):
        _init_with_projects(db_path)
        _bind_yoke(db_path)
        monkeypatch.setattr(
            project_github_auth_tokens,
            "load_github_app_control_plane_config",
            lambda: (_ for _ in ()).throw(
                GitHubAppControlPlaneConfigError(
                    "private-key file cannot be opened: /srv/private/key.pem"
                )
            ),
        )

        with pytest.raises(pga.MissingAppCredentials) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path)
        assert info.value.code == "missing_app_credentials"
        assert "/srv/private/key.pem" not in str(info.value)

    def test_token_mint_failed(self, app_bound_db: str):
        def fail_mint(**_kwargs):
            raise GitHubAppTokenError("boom")

        with pytest.raises(pga.TokenMintFailed) as info:
            pga.resolve_project_github_auth(
                "yoke",
                db_path=app_bound_db,
                token_minter=fail_mint,
            )
        assert info.value.code == "token_mint_failed"


class TestCredentialIsolation:
    def test_auth_bundle_has_no_process_environment(self, app_bound_db: str):
        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            token_minter=lambda **_kwargs: _minted("ghs_iso"),
        )

        assert result.token == "ghs_iso"
        assert not hasattr(result, "env")

    def test_local_user_provider_does_not_load_private_key(
        self, app_bound_db: str, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            project_github_auth_tokens,
            "load_github_app_control_plane_config",
            lambda: pytest.fail("local auth must not load App private key"),
        )

        with pga.bind_local_github_user_token_provider(
            lambda: "github-user-token",
            api_url="https://api.github.com",
        ):
            result = pga.resolve_project_github_auth(
                "yoke", db_path=app_bound_db,
            )

        assert result.token == "github-user-token"
        assert result.token_source == "github_app_user"
        assert result.permissions == dict(
            REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
        )

    def test_local_user_provider_error_hides_credential_path(
        self, app_bound_db: str,
    ):
        credential_path = "/private/yoke/github-app-user.json"

        def unavailable_token() -> str:
            raise RuntimeError(f"credential is missing: {credential_path}")

        with pga.bind_local_github_user_token_provider(unavailable_token):
            with pytest.raises(pga.UserAuthorizationUnavailable) as info:
                pga.resolve_project_github_auth(
                    "yoke", db_path=app_bound_db,
                )

        assert credential_path not in str(info.value)
        assert "reconnect GitHub" in str(info.value)
