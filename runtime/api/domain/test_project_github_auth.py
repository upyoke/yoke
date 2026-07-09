"""Tests for the canonical GitHub App project auth resolver."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain import db_backend, projects, project_github_auth as pga
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    InstallationToken,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo
from yoke_core.domain.project_github_binding_payload import (
    REQUIRED_AUTOMATION_PERMISSIONS,
)
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


def _apply_schema() -> None:
    return None


@pytest.fixture
def db_path(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_schema) as path:
        yield path


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _init_with_projects(db_path: str) -> None:
    projects.cmd_init(db_path=db_path)
    conn = connect(db_path)
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


def _set_app_credentials(
    db_path: str,
    *,
    project: str = "yoke",
    issuer: str = "Iv1.local",
    secret_key: str = pga.GITHUB_APP_PRIVATE_KEY_SECRET_KEY,
    private_key: str = "test-private-key",
) -> None:
    base = projects.cmd_capability_get_settings(project, "github", db_path=db_path)
    settings = {
        "auth_model": "github_app",
        "binding_table": "project_github_repo_bindings",
        "app_issuer": issuer,
        "private_key_secret_key": secret_key,
    }
    projects.cmd_capability_set_settings(
        project,
        "github",
        json.dumps(settings, sort_keys=True),
        base_settings_json=base,
        create=base is None,
        db_path=db_path,
    )
    projects.cmd_capability_set_secret(
        project,
        "github",
        secret_key,
        private_key,
        db_path=db_path,
    )


def _bind_yoke(
    db_path: str,
    *,
    repository_id: str | None = "4567",
    permissions: dict[str, str] | None = None,
    installation_status: str = "active",
    binding_status: str = "active",
) -> None:
    cmd_bind_project_repo(
        "yoke",
        installation_id="12345",
        account_id="9988",
        account_login="upyoke",
        account_type="Organization",
        github_repo="upyoke/yoke",
        repository_id=repository_id,
        default_branch="main",
        permissions=permissions or dict(REQUIRED_AUTOMATION_PERMISSIONS),
        installation_status=installation_status,
        binding_status=binding_status,
        db_path=db_path,
    )


@pytest.fixture
def app_bound_db(db_path: str) -> str:
    _init_with_projects(db_path)
    _set_app_credentials(db_path)
    _bind_yoke(db_path)
    return db_path


def _minted(token: str = "ghs_install") -> InstallationToken:
    return InstallationToken(
        token=token,
        expires_at=datetime(2026, 7, 9, 18, 0, tzinfo=timezone.utc),
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
            base_env={},
            token_minter=fake_minter,
        )

        assert isinstance(result, pga.ProjectGithubAuth)
        assert result.project == "yoke"
        assert result.repo == "upyoke/yoke"
        assert result.token == "ghs_install"
        assert result.env["GH_TOKEN"] == "ghs_install"
        assert result.installation_id == "12345"
        assert result.token_source == "github_app_installation"
        assert result.token_expires_at == "2026-07-09T18:00:00+00:00"
        assert seen["issuer"] == "Iv1.local"
        assert seen["private_key_pem"] == "test-private-key"
        assert seen["installation_id"] == "12345"
        assert seen["repository_ids"] == [4567]
        assert seen["permissions"] == dict(REQUIRED_AUTOMATION_PERMISSIONS)

    def test_uses_repository_name_when_repository_id_is_missing(self, db_path: str):
        _init_with_projects(db_path)
        _set_app_credentials(db_path)
        _bind_yoke(db_path, repository_id=None)
        seen: dict[str, Any] = {}

        def fake_minter(**kwargs):
            seen.update(kwargs)
            return _minted()

        pga.resolve_project_github_auth(
            "yoke",
            db_path=db_path,
            base_env={},
            token_minter=fake_minter,
        )

        assert seen["repositories"] == ["upyoke/yoke"]
        assert "repository_ids" not in seen

    def test_returns_frozen_bundle(self, app_bound_db: str):
        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            base_env={},
            token_minter=lambda **_kwargs: _minted(),
        )
        with pytest.raises(Exception):
            result.token = "tampered"  # type: ignore[misc]


class TestFailureModes:
    def test_missing_capability(self, db_path: str):
        _init_with_projects(db_path)

        with pytest.raises(pga.MissingCapability) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path, base_env={})
        assert info.value.code == "missing_capability"
        assert info.value.project == "yoke"

    def test_missing_repo_binding_even_when_legacy_token_exists(self, db_path: str):
        _init_with_projects(db_path)
        projects.cmd_capability_set_settings(
            "yoke",
            "github",
            json.dumps({"auth_model": "github_app", "app_issuer": "Iv1.local"}),
            base_settings_json=None,
            create=True,
            db_path=db_path,
        )
        projects.cmd_capability_set_secret(
            "yoke", "github", "token", "ghs_stranded", db_path=db_path,
        )

        with pytest.raises(pga.MissingRepoBinding) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path, base_env={})
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
                ("", 1),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(pga.MissingRepoMetadata) as info:
            pga.resolve_project_github_auth("yoke", db_path=app_bound_db, base_env={})
        assert info.value.code == "missing_repo_metadata"

    def test_missing_installation(self, app_bound_db: str):
        conn = connect(app_bound_db)
        try:
            conn.execute(
                f"DELETE FROM github_app_installations WHERE installation_id={_p(conn)}",
                ("12345",),
            )
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(pga.MissingInstallation) as info:
            pga.resolve_project_github_auth("yoke", db_path=app_bound_db, base_env={})
        assert info.value.code == "missing_installation"

    def test_binding_unavailable(self, db_path: str):
        _init_with_projects(db_path)
        _set_app_credentials(db_path)
        _bind_yoke(db_path, binding_status="unavailable")

        with pytest.raises(pga.BindingUnavailable) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path, base_env={})
        assert info.value.code == "binding_unavailable"

    def test_installation_unavailable(self, db_path: str):
        _init_with_projects(db_path)
        _set_app_credentials(db_path)
        _bind_yoke(db_path, installation_status="suspended")

        with pytest.raises(pga.InstallationUnavailable) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path, base_env={})
        assert info.value.code == "installation_unavailable"

    def test_missing_permission(self, db_path: str):
        _init_with_projects(db_path)
        _set_app_credentials(db_path)
        _bind_yoke(db_path, permissions={"metadata": "read", "issues": "read"})

        with pytest.raises(pga.MissingPermission) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path, base_env={})
        assert info.value.code == "missing_permission"
        assert "issues" in str(info.value)

    def test_missing_app_credentials(self, db_path: str):
        _init_with_projects(db_path)
        _bind_yoke(db_path)

        with pytest.raises(pga.MissingAppCredentials) as info:
            pga.resolve_project_github_auth("yoke", db_path=db_path, base_env={})
        assert info.value.code == "missing_app_credentials"

    def test_token_mint_failed(self, app_bound_db: str):
        def fail_mint(**_kwargs):
            raise GitHubAppTokenError("boom")

        with pytest.raises(pga.TokenMintFailed) as info:
            pga.resolve_project_github_auth(
                "yoke",
                db_path=app_bound_db,
                base_env={},
                token_minter=fail_mint,
            )
        assert info.value.code == "token_mint_failed"


class TestEnvIsolation:
    def test_base_env_not_mutated(self, app_bound_db: str):
        base = {"PATH": "/bin", "FOO": "bar"}
        base_snapshot = dict(base)

        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            base_env=base,
            token_minter=lambda **_kwargs: _minted("ghs_iso"),
        )

        assert result.env["GH_TOKEN"] == "ghs_iso"
        assert "GH_TOKEN" not in base
        assert base == base_snapshot

    def test_os_environ_snapshot_when_no_base_env(
        self, app_bound_db: str, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("YOKE_TEST_SENTINEL_VAR", "captured")

        result = pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            base_env=None,
            token_minter=lambda **_kwargs: _minted("ghs_snap"),
        )
        assert result.env.get("YOKE_TEST_SENTINEL_VAR") == "captured"
        assert result.env["GH_TOKEN"] == "ghs_snap"
        assert os.environ.get("GH_TOKEN") != "ghs_snap" or \
            "GH_TOKEN" not in os.environ


class TestRepairHints:
    @pytest.mark.parametrize("cls,code", [
        (pga.MissingCapability, "missing_capability"),
        (pga.MissingRepoMetadata, "missing_repo_metadata"),
        (pga.MissingRepoBinding, "missing_repo_binding"),
        (pga.MissingInstallation, "missing_installation"),
        (pga.BindingUnavailable, "binding_unavailable"),
        (pga.InstallationUnavailable, "installation_unavailable"),
        (pga.MissingPermission, "missing_permission"),
        (pga.MissingAppCredentials, "missing_app_credentials"),
        (pga.TokenMintFailed, "token_mint_failed"),
        (pga.MissingToken, "missing_token"),
        (pga.InvalidSecretSource, "invalid_secret_source"),
        (pga.InvalidToken, "invalid_token"),
        (pga.TransportFailure, "transport_failure"),
    ])
    def test_hint_per_subclass(self, cls, code):
        err = cls("buzz", "test message")
        hint = pga.repair_command_hint(err, "buzz")

        assert hint
        if code != "transport_failure":
            assert "buzz" in hint

    def test_hint_class_code_attribute(self):
        for cls in (
            pga.MissingCapability,
            pga.MissingRepoMetadata,
            pga.MissingRepoBinding,
            pga.MissingInstallation,
            pga.BindingUnavailable,
            pga.InstallationUnavailable,
            pga.MissingPermission,
            pga.MissingAppCredentials,
            pga.TokenMintFailed,
            pga.MissingToken,
            pga.InvalidSecretSource,
            pga.InvalidToken,
            pga.TransportFailure,
        ):
            assert isinstance(cls.code, str)
            assert cls.code


def test_public_surface_exports():
    expected = {
        "BindingUnavailable",
        "InstallationUnavailable",
        "InvalidSecretSource",
        "InvalidToken",
        "MissingAppCredentials",
        "MissingCapability",
        "MissingInstallation",
        "MissingPermission",
        "MissingRepoBinding",
        "MissingRepoMetadata",
        "MissingToken",
        "ProjectGithubAuth",
        "ProjectGithubAuthError",
        "TokenMintFailed",
        "TransportFailure",
        "resolve_project_github_auth",
        "repair_command_hint",
    }
    actual = set(dir(pga))
    missing = expected - actual
    assert not missing, f"missing public exports: {missing}"
