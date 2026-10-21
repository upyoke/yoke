"""agent_stop — process_dispatch_chains coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.lane_ref_test_support import (
    BUZZ_PROJECT_ID,
    seed_buzz_project,
    seed_item,
)
from yoke_core.domain.agent_stop import process_dispatch_chains
from yoke_core.domain.agent_stop_test_helpers import _init_git_repo


_UNUSED_DB_NAME = "unused.db"


@pytest.fixture
def lane_db(tmp_path):
    """YOK-42 and BUZ-42 lanes whose sequence is also a decoy's items.id."""
    with init_test_db(tmp_path) as db_path:
        conn = connect_test_db(db_path)
        try:
            seed_buzz_project(conn)
            seed_item(conn, 420, project_id=1, sequence=42, status="implementing")
            seed_item(conn, 42, project_id=1, sequence=9042, status="done")
            seed_item(
                conn,
                800,
                project_id=BUZZ_PROJECT_ID,
                sequence=42,
                status="implementing",
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


def _dirty_lane(tmp_path: Path, name: str) -> Path:
    wt = tmp_path / name
    wt.mkdir()
    _init_git_repo(wt)
    (wt / "dirty.txt").write_text("dirty\n")
    return wt


class TestProcessDispatchChains:
    def test_no_db_returns_empty_context(self, tmp_path: Path):
        ctx = process_dispatch_chains(
            db_path=str(tmp_path / "missing.db"),
            script_dir=str(tmp_path / "scripts"),
            project_root=str(tmp_path),
            agent_dir="",
            session_id="sess-1",
        )
        assert ctx.item_id == ""
        assert ctx.auto_committed is False

    def test_main_repo_basename_is_noop(self, tmp_path: Path):
        """Main repo root is a no-op — no auto-commit, no chain processing."""
        project_root = tmp_path / "repo"
        project_root.mkdir()
        _init_git_repo(project_root)

        ctx = process_dispatch_chains(
            db_path=str(tmp_path / _UNUSED_DB_NAME),
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(project_root),
            session_id="sess-1",
        )

        assert ctx.item_id == ""
        assert ctx.auto_committed is False

    @pytest.mark.parametrize(
        ("lane", "expected_item_id"), [("YOK-42", "420"), ("BUZ-42", "800")]
    )
    def test_lane_auto_commits_and_resolves_its_item(
        self, tmp_path: Path, lane_db, lane, expected_item_id
    ):
        """A public-ref lane in any project is auto-committed, and the event
        item id is the owning ``items.id``, not the number in the name."""
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = _dirty_lane(tmp_path, lane)

        ctx = process_dispatch_chains(
            db_path=lane_db,
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == expected_item_id
        assert ctx.auto_committed is True
        assert ctx.auto_commit_file_count == 1

    def test_unreadable_db_commits_nothing(self, tmp_path: Path):
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = _dirty_lane(tmp_path, "BUZ-42")

        ctx = process_dispatch_chains(
            db_path=str(tmp_path / _UNUSED_DB_NAME),
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == ""
        assert ctx.auto_committed is False

    @pytest.mark.parametrize("name", ["app-2", "python-3", "NOPE-42", "YOK-43"])
    def test_ref_shaped_folder_without_item_commits_nothing(
        self, tmp_path: Path, lane_db, name
    ):
        """A name shaped like a ref that no project item owns is not a lane."""
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = _dirty_lane(tmp_path, name)

        ctx = process_dispatch_chains(
            db_path=lane_db,
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == ""
        assert ctx.auto_committed is False

    def test_non_lane_directory_is_noop(self, tmp_path: Path, lane_db):
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = _dirty_lane(tmp_path, "scratch")

        ctx = process_dispatch_chains(
            db_path=lane_db,
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == ""
        assert ctx.auto_committed is False

    def test_clean_lane_records_item_without_commit(self, tmp_path: Path, lane_db):
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = tmp_path / "YOK-42"
        wt.mkdir()
        _init_git_repo(wt)

        ctx = process_dispatch_chains(
            db_path=lane_db,
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == "420"
        assert ctx.auto_committed is False
