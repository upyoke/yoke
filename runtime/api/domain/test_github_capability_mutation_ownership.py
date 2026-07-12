"""GitHub capability mutation stays owned by verified repo bindings."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain import db_backend, projects
from yoke_core.domain.github_app_user_verification import (
    VerifiedProjectGitHubBinding,
)
from yoke_core.domain.project_github_binding import cmd_bind_project_repo
from yoke_core.domain.projects_seed_data import CAPABILITY_TEMPLATES


_PERMISSIONS = {
    "metadata": "read",
    "issues": "write",
    "pull_requests": "write",
    "contents": "write",
    "actions": "write",
    "checks": "read",
    "workflows": "write",
    "secrets": "write",
    "actions_variables": "write",
}


@pytest.fixture
def github_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


def _bind_yoke() -> None:
    verified = VerifiedProjectGitHubBinding(
        installation_id="12345",
        account_id="9988",
        account_login="upyoke",
        account_type="Organization",
        repository_selection="selected",
        permissions=_PERMISSIONS,
        repository_id="4567",
        github_repo="upyoke/yoke",
        default_branch="main",
    )
    cmd_bind_project_repo(
        "yoke",
        installation_id="12345",
        repository_id="4567",
        github_repo="upyoke/yoke",
        expected_api_url="https://api.github.com",
        github_user_access_token="user-token",
        verifier=lambda **_kwargs: verified,
    )


def test_github_secret_reads_and_writes_stay_closed_with_retired_rows(
    github_db: str,
) -> None:
    with pytest.raises(ValueError, match="retired"):
        projects.cmd_capability_set_secret(
            "yoke", " GitHub ", "token", "new-token"
        )

    conn = pg_testdb.connect_test_database(github_db)
    try:
        conn.execute(
            "INSERT INTO capability_secrets "
            "(project_id, type, key, value, source, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (1, "github", "token", "stranded-token", "literal", "2026-07-09"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="retired and cannot be read"):
        projects.cmd_capability_get_secret("yoke", "github", "token")
    with pytest.raises(ValueError, match="retired and cannot be read"):
        projects.cmd_capability_list_secrets("yoke", "GitHub")


def test_github_full_settings_writes_are_closed_case_insensitively(
    github_db: str,
) -> None:
    with pytest.raises(ValueError, match="binding-owned"):
        projects.cmd_capability_set_settings(
            "yoke", "GITHUB", '{"token":"secret"}', create=True
        )


def test_github_optional_merge_requires_a_bound_capability(github_db: str) -> None:
    with pytest.raises(ValueError, match="existing GitHub App repo binding"):
        projects.cmd_capability_merge_settings(
            "yoke", "github", {"ci_oidc_manage_provider": True}
        )


def test_github_optional_boolean_merge_preserves_binding_projection(
    github_db: str,
) -> None:
    _bind_yoke()

    projects.cmd_capability_merge_settings(
        "yoke", " GitHub ", {"ci_oidc_manage_provider": False}
    )

    stored = json.loads(
        projects.cmd_capability_get_settings("yoke", "github") or "{}"
    )
    assert stored == {
        "api_url": "https://api.github.com",
        "ci_oidc_manage_provider": False,
        "installation_id": "12345",
        "permissions": _PERMISSIONS,
        "repo_name": "yoke",
        "repo_owner": "upyoke",
        "repository_id": "4567",
    }


@pytest.mark.parametrize(
    "assignments, message",
    [
        ({"token": "secret"}, "only ci_oidc_manage_provider"),
        ({"private_key": "secret"}, "only ci_oidc_manage_provider"),
        ({"repo_name": "other"}, "only ci_oidc_manage_provider"),
        ({"ci_oidc_manage_provider": "false"}, "must be a boolean"),
    ],
)
def test_github_merge_rejects_nonoptional_or_nonboolean_settings(
    github_db: str,
    assignments: dict[str, object],
    message: str,
) -> None:
    _bind_yoke()
    with pytest.raises(ValueError, match=message):
        projects.cmd_capability_merge_settings("yoke", "github", assignments)


def test_github_merge_refuses_a_corrupt_existing_projection(github_db: str) -> None:
    _bind_yoke()
    conn = pg_testdb.connect_test_database(github_db)
    try:
        conn.execute(
            "UPDATE project_capabilities SET settings=%s "
            "WHERE project_id=1 AND type='github'",
            ('{"repo_owner":"upyoke","token":"stranded"}',),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="do not match the verified binding"):
        projects.cmd_capability_merge_settings(
            "yoke", "github", {"ci_oidc_manage_provider": True}
        )


def test_cli_rejects_github_secret_and_full_settings_writes(
    github_db: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert projects.main([
        "capability-set-secret", "yoke", "GitHub", "token", "secret",
    ]) == 2
    assert "retired" in capsys.readouterr().err

    assert projects.main([
        "capability-get-secret", "yoke", "github", "token",
    ]) == 2
    read_error = capsys.readouterr()
    assert "retired and cannot be read" in read_error.err
    assert "token" not in read_error.out

    assert projects.main([
        "capability-list-secrets", "yoke", "GITHUB",
    ]) == 2
    assert "retired and cannot be read" in capsys.readouterr().err

    assert projects.main([
        "capability-set-settings", "yoke", "github", "{}", "--new",
    ]) == 2
    assert "binding-owned" in capsys.readouterr().err


def test_capability_template_documents_optional_oidc_boolean() -> None:
    github = next(row for row in CAPABILITY_TEMPLATES if row[0] == "github")
    config = {item["key"]: item for item in json.loads(github[3])}
    assert config["ci_oidc_manage_provider"]["secret"] is False
