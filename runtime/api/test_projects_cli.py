"""CLI ``main(argv)`` tests for ``yoke_core.domain.projects``.

Each test runs against a backend-appropriate disposable DB via
:func:`init_test_db`. The previous "temp file + ``cmd_init``" pattern shared one
database on Postgres (``main`` resolves its connection from the backend factory,
whose Postgres target is the DSN, not ``YOKE_DB``), so capability upserts and
``github_repo`` mutations from one test leaked into another. ``cmd_init`` now
routes catalog probes through backend-aware schema helpers. The ``YOKE_DB`` pin
still drives SQLite resolution and stays a harmless no-op on Postgres; it is set
inside the ``init_test_db`` context so the repointed DSN governs the read.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import projects
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_seed_test_helpers import (
    seed_externalwebapp_site_environments as _seed_externalwebapp_environments,
    seed_project_identities,
)
from runtime.api.fixtures.file_test_db import init_test_db


def _apply_no_schema() -> None:
    """Strategy for tests that run ``cmd_init`` themselves."""
    return None


def _apply_projects_schema() -> None:
    """Strategy seeding the full project schema."""
    projects.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


@pytest.fixture
def empty_db(tmp_path: Path) -> Iterator[str]:
    """Disposable DB token for tests that run ``init`` themselves."""
    with init_test_db(tmp_path, apply_schema=_apply_no_schema) as path:
        yield path


@pytest.fixture
def initialized_db(tmp_path: Path) -> Iterator[str]:
    """Disposable DB token after running ``cmd_init`` (tables + seed exist)."""
    with init_test_db(tmp_path, apply_schema=_apply_projects_schema) as path:
        yield path


@pytest.fixture
def pinned_db(initialized_db: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """``initialized_db`` pinned at ``YOKE_DB`` via monkeypatch.

    Set inside the ``init_test_db`` context (``initialized_db`` is still
    yielding) so the Postgres DSN repoint governs the read; on SQLite the pin
    drives resolution. Restoring through monkeypatch preserves a prior
    conftest-pinned value (e.g. the auto-pinned canonical) on teardown instead
    of deleting the env entry and leaving later tests on fallback resolution.
    """
    monkeypatch.setenv("YOKE_DB", initialized_db)
    return initialized_db


class TestMainCli:
    def test_no_command_returns_2(self, initialized_db: str):
        rc = projects.main([])
        assert rc == 2

    def test_init_returns_0(self, empty_db: str, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("YOKE_DB", empty_db)
        assert projects.main(["init"]) == 0

    def test_create_returns_0(self, pinned_db: str, capsys):
        rc = projects.main(["create", "cli-proj", "CLI Project"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "cli-proj" in captured.out.lower()

    def test_get_returns_0(self, pinned_db: str, capsys):
        rc = projects.main(["get", "yoke"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "yoke" in captured.out.lower()

    def test_get_field_returns_0(self, pinned_db: str, capsys):
        rc = projects.main(["get", "yoke", "name"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Yoke" in captured.out

    def test_get_not_found_returns_1(self, pinned_db: str):
        assert projects.main(["get", "nonexistent"]) == 1

    def test_get_invalid_field_returns_2(self, pinned_db: str):
        assert projects.main(["get", "yoke", "bogus"]) == 2

    def test_list_returns_0(self, pinned_db: str, capsys):
        rc = projects.main(["list"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "yoke" in captured.out

    def test_update_returns_0(self, pinned_db: str, capsys):
        rc = projects.main(["update", "yoke", "github_repo", "owner/yoke"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Updated" in captured.out

    def test_update_not_found_returns_1(self, pinned_db: str):
        assert projects.main(["update", "ghost", "github_repo", "val"]) == 1

    def test_has_capability_present_returns_0(self, pinned_db: str):
        projects.main(["capability-set-settings", "externalwebapp", "deploy", "{}", "--new"])
        assert projects.main(["has-capability", "externalwebapp", "deploy"]) == 0

    def test_has_capability_absent_returns_1(self, pinned_db: str):
        assert projects.main(["has-capability", "yoke", "nonexistent"]) == 1

    def test_capability_list_returns_0(self, pinned_db: str, capsys):
        projects.main(["capability-set-settings", "yoke", "ssh", '{}', "--new"])
        rc = projects.main(["capability-list", "yoke"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "ssh" in captured.out

    def test_capability_get_settings_returns_0(self, pinned_db: str, capsys):
        projects.main(
            ["capability-set-settings", "yoke", "ssh", '{"user":"root"}', "--new"]
        )
        rc = projects.main(["capability-get-settings", "yoke", "ssh"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "root" in captured.out

    def test_capability_get_settings_not_found_returns_1(self, pinned_db: str):
        assert projects.main(["capability-get-settings", "yoke", "nonexistent"]) == 1

    def test_capability_set_settings_new_returns_0(self, pinned_db: str, capsys):
        assert projects.main(
            ["capability-set-settings", "yoke", "ssh", '{"k":"v"}', "--new"]
        ) == 0

    def test_capability_set_settings_without_base_returns_2(
        self, pinned_db: str, capsys
    ):
        assert projects.main(
            ["capability-set-settings", "yoke", "nope", '{}']
        ) == 2
        assert "--base is required" in capsys.readouterr().err

    def test_capability_merge_settings_returns_0(self, pinned_db: str, capsys):
        assert projects.main(
            ["capability-merge-settings", "yoke", "nope", "--set", "enabled=true"]
        ) == 0

    def test_capability_set_secret_returns_0(self, pinned_db: str, capsys):
        rc = projects.main(["capability-set-secret", "yoke", "deploy", "tok", "abc"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "tok" in captured.out
        assert "abc" not in captured.out

    def test_capability_set_secret_value_file_imports_literal(
        self, pinned_db: str, tmp_path: Path, capsys
    ):
        secret_path = tmp_path / "secret.txt"
        secret_path.write_text("file-secret\n", encoding="utf-8")

        rc = projects.main([
            "capability-set-secret", "yoke", "deploy", "tok",
            "--value-file", str(secret_path),
        ])

        assert rc == 0
        captured = capsys.readouterr()
        assert "file-secret" not in captured.out
        secret_path.write_text("changed\n", encoding="utf-8")
        assert projects.cmd_capability_get_secret(
            "yoke", "deploy", "tok", db_path=pinned_db,
        ) == "file-secret"

    def test_capability_set_secret_value_stdin_imports_literal(
        self, pinned_db: str, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        monkeypatch.setattr("sys.stdin", io.StringIO("stdin-secret\n"))

        rc = projects.main([
            "capability-set-secret", "yoke", "deploy", "tok",
            "--value-stdin",
        ])

        assert rc == 0
        captured = capsys.readouterr()
        assert "stdin-secret" not in captured.out
        assert projects.cmd_capability_get_secret(
            "yoke", "deploy", "tok", db_path=pinned_db,
        ) == "stdin-secret"

    def test_capability_get_secret_returns_0(self, pinned_db: str, capsys):
        projects.main(["capability-set-secret", "yoke", "deploy", "tok", "abc"])
        rc = projects.main(["capability-get-secret", "yoke", "deploy", "tok"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "abc" in captured.out

    def test_capability_get_secret_not_found_returns_1(self, pinned_db: str):
        assert projects.main(["capability-get-secret", "yoke", "nope", "nope"]) == 1

    def test_capability_list_secrets_returns_0(self, pinned_db: str, capsys):
        projects.main(["capability-set-secret", "yoke", "ssh", "k1", "v1"])
        rc = projects.main(["capability-list-secrets", "yoke", "ssh"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "k1" in captured.out

    def test_resolve_deploy_envs_returns_0(self, pinned_db: str, capsys):
        conn = connect(pinned_db)
        try:
            _seed_externalwebapp_environments(conn)
        finally:
            conn.close()
        rc = projects.main(["resolve-deploy-envs", "externalwebapp"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "production" in captured.out

    def test_resolve_deploy_envs_not_found_returns_1(self, pinned_db: str):
        projects.cmd_create("empty2", "Empty2", db_path=pinned_db)
        assert projects.main(["resolve-deploy-envs", "empty2"]) == 1
