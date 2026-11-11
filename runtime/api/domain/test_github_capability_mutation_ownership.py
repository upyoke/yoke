"""GitHub capability mutation stays owned by verified repo bindings."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import projects
from yoke_core.domain.projects_seed_data import CAPABILITY_TEMPLATES


@pytest.fixture
def github_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    with pg_testdb.test_database() as database:
        db_name = database.info.dbname
        yield db_name


def test_github_secret_reads_and_writes_stay_closed_with_retired_rows(
    github_db: str,
) -> None:
    with pytest.raises(ValueError, match="retired"):
        projects.cmd_capability_set_secret("yoke", " GitHub ", "token", "new-token")

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


@pytest.mark.parametrize(
    "assignments",
    [{"token": "secret"}, {"repo_name": "other"}, {"ci_oidc_manage_provider": True}],
)
def test_github_merges_are_closed(assignments: dict[str, object]) -> None:
    """Assignment validation refuses before any database read."""
    with pytest.raises(ValueError, match="binding-owned; merge-settings is refused"):
        projects.cmd_capability_merge_settings("yoke", " GitHub ", assignments)


def test_cli_rejects_github_secret_and_full_settings_writes(
    github_db: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        projects.main(
            [
                "capability-set-secret",
                "yoke",
                "GitHub",
                "token",
                "secret",
            ]
        )
        == 2
    )
    assert "retired" in capsys.readouterr().err

    assert (
        projects.main(
            [
                "capability-get-secret",
                "yoke",
                "github",
                "token",
            ]
        )
        == 2
    )
    read_error = capsys.readouterr()
    assert "retired and cannot be read" in read_error.err
    assert "token" not in read_error.out

    assert (
        projects.main(
            [
                "capability-list-secrets",
                "yoke",
                "GITHUB",
            ]
        )
        == 2
    )
    assert "retired and cannot be read" in capsys.readouterr().err

    assert (
        projects.main(
            [
                "capability-set-settings",
                "yoke",
                "github",
                "{}",
                "--new",
            ]
        )
        == 2
    )
    assert "binding-owned" in capsys.readouterr().err


def test_capability_template_lists_only_binding_fields() -> None:
    github = next(row for row in CAPABILITY_TEMPLATES if row[0] == "github")
    keys = [item["key"] for item in json.loads(github[3])]
    assert keys == ["repo_owner", "repo_name", "installation_id", "repository_id"]
