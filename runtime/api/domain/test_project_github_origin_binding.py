"""GitHub deployment-origin and binding ownership boundaries."""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

import pytest

from runtime.api.domain.project_github_auth_test_support import (
    app_bound_db as app_bound_db,
    control_plane_config as control_plane_config,
    db_path as db_path,
)
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_contracts.github_origin import validate_github_api_endpoint
from yoke_core.domain import db_backend, project_github_auth as pga
from yoke_core.domain.github_app_control_plane import GitHubAppControlPlaneConfig
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import (
    ProjectGithubBindingError,
    cmd_bind_project_repo,
    cmd_project_github_binding_status,
)


def _verified(
    *,
    github_repo: str,
    repository_id: str = "4567",
    api_url: str = "https://api.github.com",
) -> VerifiedProjectGitHubBinding:
    return VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="Example-Org",
        account_type="Organization",
        repository_selection="selected",
        permissions={
            "metadata": "read",
            "issues": "write",
            "pull_requests": "write",
            "contents": "write",
            "actions": "write",
            "checks": "read",
            "workflows": "write",
            "secrets": "write",
            "variables": "write",
        },
        repository_id=repository_id,
        github_repo=github_repo,
        default_branch="main",
        api_url=api_url,
    )


def _bind(project: str, verified: VerifiedProjectGitHubBinding) -> None:
    cmd_bind_project_repo(
        project,
        installation_id=verified.installation_id,
        github_repo=verified.github_repo,
        repository_id=verified.repository_id,
        expected_api_url=verified.api_url,
        github_user_access_token="github-user-token",
        verifier=lambda **kwargs: verified,
    )


@pytest.fixture
def binding_database(monkeypatch: pytest.MonkeyPatch):
    db_name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(db_name)
    try:
        apply_fixture_schema(conn)
    finally:
        conn.close()
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV,
        pg_testdb.dsn_for_test_database(db_name),
    )
    try:
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


def test_binding_rejects_installation_id_reuse_across_github_origins(
    binding_database,
) -> None:
    _bind("buzz", _verified(github_repo="example-org/buzz"))
    enterprise = _verified(
        github_repo="example-org/yoke",
        repository_id="4568",
        api_url="https://github.example/api/v3",
    )

    with pytest.raises(
        ProjectGithubBindingError,
        match="different GitHub API origin",
    ):
        _bind("yoke", enterprise)


def test_installation_origin_invariant_is_enforced_inside_upsert(
    binding_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind("buzz", _verified(github_repo="example-org/buzz"))
    enterprise = _verified(
        github_repo="example-org/yoke",
        repository_id="4568",
        api_url="https://github.example/api/v3",
    )
    from yoke_core.domain import project_github_binding_persistence as persistence

    monkeypatch.setattr(persistence, "query_one", lambda *args, **kwargs: None)

    with pytest.raises(
        ProjectGithubBindingError,
        match="different GitHub API origin",
    ):
        _bind("yoke", enterprise)


def test_binding_reports_repository_already_owned_by_another_project(
    binding_database,
) -> None:
    verified = _verified(github_repo="example-org/buzz")
    _bind("buzz", verified)

    with pytest.raises(
        ProjectGithubBindingError,
        match="already bound to another project",
    ):
        _bind("yoke", verified)


def test_status_reports_binding_installation_origin_mismatch(
    binding_database,
) -> None:
    _bind("buzz", _verified(github_repo="example-org/buzz"))
    conn = pg_testdb.connect_test_database(binding_database)
    try:
        conn.execute(
            "UPDATE project_github_repo_bindings SET api_url=%s "
            "WHERE project_id=2",
            ("https://github.example/api/v3",),
        )
        conn.commit()
    finally:
        conn.close()

    status = cmd_project_github_binding_status("buzz")
    assert status["automation"] == {
        "available": False,
        "reason": "api_origin_mismatch",
    }


def test_hosted_credentials_must_match_bound_github_origin(
    app_bound_db: str,
) -> None:
    enterprise_config = GitHubAppControlPlaneConfig(
        issuer="Iv1.enterprise",
        private_key_pem="enterprise-private-key",
        endpoint=validate_github_api_endpoint("https://github.example/api/v3"),
        private_key_file="/run/secrets/enterprise-github-app-key",
    )

    with pytest.raises(pga.MissingAppCredentials, match="do not match"):
        pga.resolve_project_github_auth(
            "yoke",
            db_path=app_bound_db,
            control_plane_config=enterprise_config,
            token_minter=lambda **_kwargs: pytest.fail(
                "origin mismatch must fail before token minting"
            ),
        )


def test_local_user_provider_must_match_bound_github_origin(
    app_bound_db: str,
) -> None:
    called = False

    def token_provider() -> str:
        nonlocal called
        called = True
        return "github-user-token"

    with pga.bind_local_github_user_token_provider(
        token_provider,
        api_url="https://github.example/api/v3",
    ):
        with pytest.raises(pga.UserAuthorizationUnavailable, match="does not match"):
            pga.resolve_project_github_auth(
                "yoke", db_path=app_bound_db,
            )

    assert called is False
