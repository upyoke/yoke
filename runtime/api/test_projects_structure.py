"""Coexistence assertions between coarse ``projects`` and the Project Structure aggregate (path registry identity layer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import projects
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.schema_common import _get_columns
from runtime.api.fixtures.file_test_db import init_test_db


def _init_with_baseline_projects() -> None:
    """``cmd_init`` plus the two baseline test-project identity rows."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import (
        seed_project_identities,
    )

    projects.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()


@pytest.fixture
def initialized_db(tmp_path: Path) -> str:
    with init_test_db(tmp_path, apply_schema=_init_with_baseline_projects) as db_path:
        yield db_path


class TestProjectStructureCoexistence:
    """Assertions about the post-Phase-0 ``projects`` shape.

    Every Phase 0 cutover-proof slice retired its coarse ``projects``
    column(s) into a Project Structure family. The ``projects`` table now
    holds only identity / repo-host metadata; per-project structured settings
    live in Project Structure (``command_definitions``, ``deploy_defaults``,
    ``merge_verification``, ``context_routing``).
    """

    _EXPECTED_PROJECTS_COLUMNS = {
        "id",
        "slug",
        "name",
        "emoji",
        "default_branch",
        "github_repo",
        "public_item_prefix",
        # Per-project GitHub sync switch — a project-wide stance on the
        # repo-host relationship, so it lives on projects, not in a
        # Project Structure family (yoke_core.domain.projects_github_sync_mode).
        "github_sync_mode",
        "created_at",
    }

    def _projects_columns(self, db_path: str) -> set:
        conn = connect(db_path)
        try:
            return set(_get_columns(conn, "projects"))
        finally:
            conn.close()

    def test_projects_columns_unchanged_after_project_structure_init(
        self, initialized_db: str
    ):
        """Initializing the Project Structure aggregate leaves ``projects``
        column set untouched, and none of the Phase 0 retired columns
        re-appear."""
        from yoke_core.domain import project_structure as ps
        before = self._projects_columns(initialized_db)
        ps.cmd_init(db_path=initialized_db)
        after = self._projects_columns(initialized_db)
        assert before == after == self._EXPECTED_PROJECTS_COLUMNS, (
            "Project Structure init must not modify the projects table. "
            f"Diff: {before.symmetric_difference(after)}"
        )

    def test_replaced_coarse_test_command_columns_stay_dropped(
        self, initialized_db: str
    ):
        """The four coarse project-level test-command columns whose replacement
        is the ``command_definitions`` Project Structure family must remain
        dropped. This test guards against reintroduction without naming the
        retired columns directly."""
        after = self._projects_columns(initialized_db)
        from yoke_core.domain import command_definitions as cmd_defs
        revived = [c for c in after
                   if c.startswith("test_command_")
                   and c.split("_", 2)[-1] in cmd_defs.SCOPES]
        assert not revived, (
            f"Coarse project-level test-command column(s) were reintroduced: "
            f"{revived}. The canonical source is the ``command_definitions`` "
            f"Project Structure family."
        )

    def test_project_structure_tables_do_not_duplicate_projects_columns(
        self, initialized_db: str
    ):
        """No replacement-family table lands in path registry identity layer (path registry envelope contract envelope-only)."""
        from yoke_core.domain import project_structure as ps
        ps.cmd_init(db_path=initialized_db)
        conn = connect(initialized_db)
        try:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=current_schema() "
                "AND table_name LIKE 'project_structure%'"
            ).fetchall()
            ps_tables = {r[0] for r in rows}
        finally:
            conn.close()
        assert ps_tables == {"project_structure"}

    def test_seeded_projects_remain_gettable_via_coarse_surface(
        self, initialized_db: str
    ):
        """Seeding the Project Structure aggregate must not disturb
        coarse-project reads."""
        from yoke_core.domain import command_definitions as cmd_defs
        from yoke_core.domain import project_structure as ps
        ps.cmd_init(db_path=initialized_db)
        ps.cmd_seed("yoke", db_path=initialized_db)
        ps.cmd_seed("buzz", db_path=initialized_db)
        # Coarse-project reads still work.
        assert projects.cmd_get("yoke", db_path=initialized_db) is not None
        assert projects.cmd_get("buzz", db_path=initialized_db) is not None
        # The ``smoke`` scope is readable through the Project Structure
        # surface rather than the coarse ``projects`` table.
        assert cmd_defs.get_command(
            "buzz", "smoke", db_path=initialized_db
        ) == "cd app/web && npm run test:smoke"
