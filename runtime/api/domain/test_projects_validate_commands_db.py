"""DB-backed integration tests for the project test-command validator.

Pure-unit (no DB) tests live in test_projects_validate_commands.py.
"""

from __future__ import annotations

import stat
import zlib
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import command_definitions as cmd_defs
from yoke_core.domain import db_backend
from yoke_core.domain import project_structure as ps
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.projects import (
    cmd_validate_test_commands,
    validate_project_test_commands,
)
from yoke_core.domain.project_identity import DEFAULT_PUBLIC_ITEM_PREFIX
from yoke_core.domain.projects_restart_schema import _projects_table_sql
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _numeric_project_id(project_id: str) -> int:
    if project_id in SEED_PROJECT_IDS:
        return SEED_PROJECT_IDS[project_id]
    return 1000 + (zlib.adler32(project_id.encode("utf-8")) % 900000)


def _apply_projvalidate_schema() -> None:
    """``apply_schema`` strategy for :func:`init_test_db`.

    The validator reads ``projects`` and the Project Structure tables that
    house ``command_definitions``. The default ``schema.cmd_init`` builds
    neither, so this closure creates the minimal ``projects`` table on the
    backend-resolved connection and then runs ``ps.cmd_init`` for the Project
    Structure tables. Both resolve their connection from the active backend
    (``YOKE_DB`` on SQLite, the repointed ``YOKE_PG_DSN`` on Postgres), so
    the seeds the validator reads land in the same per-test database.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(
            conn,
            _projects_table_sql(if_not_exists=False)
        )
        conn.commit()
    finally:
        conn.close()
    ps.cmd_init()


def _insert_project(
    db_path: str,
    project_id: str,
    repo_path: str,
    quick: str = "",
    full: str = "",
    e2e: str = "",
    smoke: str = "",
) -> None:
    conn = connect_test_db(db_path)
    try:
        p = _p(conn)
        numeric_project_id = _numeric_project_id(project_id)
        conn.execute(
            f"""INSERT INTO projects
               (id, slug, name, public_item_prefix, created_at)
               VALUES ({p}, {p}, {p}, {p}, {p})
               ON CONFLICT (id) DO UPDATE SET
                 slug = excluded.slug,
                 name = excluded.name,
                 public_item_prefix = excluded.public_item_prefix,
                 created_at = excluded.created_at""",
            (
                numeric_project_id,
                project_id,
                project_id.title(),
                DEFAULT_PUBLIC_ITEM_PREFIX,
                "2026-04-20T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if repo_path:
        register_machine_checkout(
            Path(repo_path).parent / "machine-config",
            Path(repo_path),
            _numeric_project_id(project_id),
            create_checkout=False,
        )

    seeds = {"quick": quick, "full": full, "e2e": e2e, "smoke": smoke}
    seeds = {s: v for s, v in seeds.items() if v}
    if not seeds:
        return
    ps.apply_patch(
        project_id,
        ops=[
            {
                "op": "put",
                "family": "command_definitions",
                "attachment": "project",
                "entry_key": scope,
                "payload": {"command": command},
            }
            for scope, command in seeds.items()
        ],
        db_path=db_path,
    )


def _make_script(path: Path) -> None:
    """Create an executable shell script at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env sh\necho test\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def yoke_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    # Backend-aware per-test DB: a real file on SQLite, a disposable per-test
    # database on Postgres (YOKE_PG_DSN repointed for the context). Isolation
    # is load-bearing: without it the Postgres tests share the DSN-pointed
    # database and the raw-seed projects rows the validator reads never land in
    # the database the validator's backend-aware connect() opens.
    with init_test_db(tmp_path, apply_schema=_apply_projvalidate_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestValidateProjectCommands:
    """Test the DB-backed project validator and CLI entrypoint."""

    def test_valid_project_exit_zero(self, yoke_db: str, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_script(repo / "scripts/run-tests.sh")
        (repo / "package.json").write_text('{"name":"repo"}\n')
        _insert_project(
            yoke_db,
            "validproj",
            str(repo),
            quick="sh scripts/run-tests.sh --fast",
            full="sh scripts/run-tests.sh",
            e2e="npm run test:e2e",
            smoke="npm run test:smoke",
        )

        output, exit_code = cmd_validate_test_commands(
            project_id="validproj", db_path=str(yoke_db)
        )

        assert exit_code == 0
        assert "project=validproj" in output
        for scope in cmd_defs.SCOPES:
            assert f"{scope}=valid|" in output

    def test_empty_project_all_empty_exit_zero(
        self, yoke_db: str, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _insert_project(yoke_db, "emptyproj", str(repo))

        output, exit_code = cmd_validate_test_commands(
            project_id="emptyproj", db_path=str(yoke_db)
        )

        assert exit_code == 0
        for scope in cmd_defs.SCOPES:
            assert f"{scope}=empty|" in output

    def test_empty_e2e_is_not_configured_not_invalid(
        self, yoke_db: str, tmp_path: Path
    ) -> None:
        """Contract: an absent or empty command_definitions scope => 'empty'
        (not configured), never 'invalid'. Buzz relies on this for ``e2e``
        because it has no real E2E suite today."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _make_script(repo / "scripts/run.sh")
        (repo / "package.json").write_text('{"name":"repo"}\n')
        _insert_project(
            yoke_db,
            "partial",
            str(repo),
            quick="sh scripts/run.sh",
            full="sh scripts/run.sh",
            e2e="",
            smoke="npm run test:smoke",
        )

        output, exit_code = cmd_validate_test_commands(
            project_id="partial", db_path=str(yoke_db)
        )

        assert exit_code == 0
        assert "e2e=empty|" in output
        assert "e2e=invalid|" not in output
        assert "smoke=valid|" in output

    def test_invalid_project_exit_one(
        self, yoke_db: str, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _insert_project(
            yoke_db,
            "badproj",
            str(repo),
            quick="sh scripts/nonexistent.sh",
            full="sh scripts/also-missing.sh",
            e2e="npm run test:e2e",
            smoke="npm run test:smoke",
        )

        output, exit_code = cmd_validate_test_commands(
            project_id="badproj", db_path=str(yoke_db)
        )

        assert exit_code == 1
        for scope in cmd_defs.SCOPES:
            assert f"{scope}=invalid|" in output
        assert "nonexistent" in output

    def test_missing_checkout_mapping_marks_all_invalid(
        self, yoke_db: str
    ) -> None:
        _insert_project(
            yoke_db,
            "noroot",
            "",
            quick="sh scripts/run-tests.sh",
        )

        output, exit_code = cmd_validate_test_commands(
            project_id="noroot", db_path=str(yoke_db)
        )

        assert exit_code == 1
        for scope in cmd_defs.SCOPES:
            assert f"{scope}=invalid|" in output
        assert "has no machine-local checkout mapping" in output

    def test_unusable_checkout_mapping_marks_all_invalid(
        self, yoke_db: str, tmp_path: Path
    ) -> None:
        bogus = tmp_path / "does-not-exist"
        _insert_project(
            yoke_db,
            "bogus",
            str(bogus),
            quick="sh scripts/run-tests.sh",
        )

        output, exit_code = cmd_validate_test_commands(
            project_id="bogus", db_path=str(yoke_db)
        )

        assert exit_code == 1
        assert "mapped checkout not a directory" in output

    def test_all_mode_aggregates_and_reports_mixed_results(
        self, yoke_db: str, tmp_path: Path
    ) -> None:
        good_repo = tmp_path / "good"
        good_repo.mkdir()
        _make_script(good_repo / "scripts/run.sh")

        bad_repo = tmp_path / "bad"
        bad_repo.mkdir()

        _insert_project(
            yoke_db,
            "alpha",
            str(good_repo),
            quick="sh scripts/run.sh",
        )
        _insert_project(
            yoke_db,
            "beta",
            str(bad_repo),
            quick="sh scripts/missing.sh",
        )

        output, exit_code = cmd_validate_test_commands(
            all_projects=True, db_path=str(yoke_db)
        )

        assert "project=alpha" in output
        assert "project=beta" in output
        assert "quick=valid|" in output   # alpha
        assert "quick=invalid|" in output  # beta
        assert exit_code == 1

    def test_all_mode_zero_projects_exits_zero(self, yoke_db: str) -> None:
        output, exit_code = cmd_validate_test_commands(
            all_projects=True, db_path=str(yoke_db)
        )
        assert exit_code == 0
        assert output == ""

    def test_usage_errors_raise_value_error(self, yoke_db: str) -> None:
        with pytest.raises(ValueError):
            cmd_validate_test_commands(db_path=str(yoke_db))
        with pytest.raises(ValueError):
            cmd_validate_test_commands(
                project_id="alpha", all_projects=True, db_path=str(yoke_db)
            )

    def test_unknown_project_raises_lookup_error(self, yoke_db: str) -> None:
        with pytest.raises(LookupError):
            validate_project_test_commands("ghost", db_path=str(yoke_db))
