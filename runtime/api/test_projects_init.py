"""Init / seed-data tests for ``yoke_core.domain.projects``.

Each test runs against a backend-appropriate disposable DB via
:func:`init_test_db`. ``cmd_init`` creates the project-registry tables and
seeds only project-agnostic vocabulary (capability templates); a fresh
universe carries NO project rows — projects enter through onboarding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import projects
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_common import _get_tables
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_no_schema() -> None:
    """Strategy for tests that run ``cmd_init`` themselves."""
    return None


def _apply_projects_schema() -> None:
    """Strategy seeding the full project-registry schema."""
    projects.cmd_init()


@pytest.fixture
def empty_db(tmp_path: Path) -> Iterator[str]:
    """Disposable DB token for tests that run ``cmd_init`` themselves.

    The no-op ``apply_schema`` preserves an empty disposable DB; the test owns
    the ``cmd_init`` call.
    """
    with init_test_db(tmp_path, apply_schema=_apply_no_schema) as path:
        yield path


@pytest.fixture
def initialized_db(tmp_path: Path) -> Iterator[str]:
    """Disposable DB token after running ``cmd_init`` (tables + vocabulary)."""
    with init_test_db(tmp_path, apply_schema=_apply_projects_schema) as path:
        yield path


class TestInit:
    def test_creates_tables(self, empty_db: str):
        projects.cmd_init(db_path=empty_db)
        conn = connect_test_db(empty_db)
        try:
            tables = set(_get_tables(conn))
            for expected in (
                "projects",
                "sites",
                "environments",
                "capability_templates",
                "project_capabilities",
                "ephemeral_environments",
                "capability_secrets",
            ):
                assert expected in tables, f"Missing table: {expected}"
        finally:
            conn.close()

    def test_seeds_no_project_rows(self, initialized_db: str):
        """A fresh universe carries no projects — onboarding adds them."""
        conn = connect_test_db(initialized_db)
        try:
            for table in ("projects", "sites", "environments"):
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                assert count == 0, f"{table} must start empty, has {count}"
        finally:
            conn.close()

    def test_seeds_capability_templates(self, initialized_db: str):
        conn = connect_test_db(initialized_db)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM capability_templates"
            ).fetchone()[0]
            assert count >= 5  # ssh, docker, github, etc.
            ci_row = conn.execute(
                "SELECT COUNT(*) FROM capability_templates "
                "WHERE id='ci_workflow_file'"
            ).fetchone()[0]
            assert ci_row == 1
        finally:
            conn.close()

    def test_creates_project_structure_tables_without_entries(
        self, initialized_db: str
    ):
        """The aggregate tables exist; per-project entries come from
        project onboarding, never from init."""
        conn = connect_test_db(initialized_db)
        try:
            assert "project_structure" in set(_get_tables(conn))
            count = conn.execute(
                "SELECT COUNT(*) FROM project_structure"
            ).fetchone()[0]
            assert count == 0
        finally:
            conn.close()

    def test_idempotent(self, empty_db: str):
        """Running init twice must not raise or duplicate seed data."""
        projects.cmd_init(db_path=empty_db)
        projects.cmd_init(db_path=empty_db)

        conn = connect_test_db(empty_db)
        try:
            counts = conn.execute(
                "SELECT id, COUNT(*) FROM capability_templates "
                "GROUP BY id HAVING COUNT(*) > 1"
            ).fetchall()
            assert counts == []
        finally:
            conn.close()

    def test_reinit_preserves_onboarded_project_edits(self, empty_db: str):
        """Re-running ``cmd_init`` after a project onboarded (identity row +
        Project Structure seed) leaves operator-edited command_definitions
        alone — init never touches per-project entries."""
        from yoke_core.domain import command_definitions as cmd_defs
        from yoke_core.domain import project_structure as ps

        projects.cmd_init(db_path=empty_db)
        conn = connect(empty_db)
        try:
            seed_project_identities(conn)
        finally:
            conn.close()
        ps.cmd_seed("yoke", db_path=empty_db)

        # Operator edit: override the full scope with a different command.
        ps.apply_patch(
            "yoke",
            ops=[{
                "op": "put",
                "family": "command_definitions",
                "attachment": "project",
                "entry_key": "full",
                "payload": {"command": "custom-full-command"},
            }],
            db_path=empty_db,
        )

        projects.cmd_init(db_path=empty_db)

        commands = cmd_defs.list_commands("yoke", db_path=empty_db)
        assert commands["full"] == "custom-full-command"
