"""Tests for merge_worktree: dirty-state, locks, preflight, generated files.

Other merge_worktree tests live in test_merge_worktree.py,
test_merge_worktree_views.py, and test_merge_worktree_sync.py.

Pytest fixture (mw_db) shared via _merge_worktree_test_helpers (private module).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.engines import merge_worktree
from yoke_core.engines.merge_worktree import (
    MergeArgs,
    MergeContext,
    extract_generated_files,
)

from yoke_core.engines._merge_worktree_test_helpers import mw_db


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestRootDirtyState:
    def _init_repo(self, repo: Path) -> None:
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test User"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            check=True,
            capture_output=True,
            text=True,
        )
        (repo / "README.md").write_text("initial\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "README.md"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_user_authored_dirty_files_block(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        self._init_repo(repo)
        (repo / "README.md").write_text("changed\n")

        messages: list[str] = []
        monkeypatch.setattr(
            merge_worktree,
            "_print",
            lambda msg="", err=False: messages.append(msg),
        )

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(repo)

        result = merge_worktree.check_and_clean_root_dirty_state(ctx)

        assert result == (4, "user-authored files in repo root")
        assert any("README.md" in message for message in messages)

    def test_yoke_managed_dirty_files_auto_commit_from_explicit_repo_root(
        self, tmp_path, monkeypatch
    ):
        repo = tmp_path / "repo"
        self._init_repo(repo)
        (repo / "ouroboros").mkdir()
        (repo / "ouroboros" / "simulation-YOK-9999.md").write_text("managed\n")
        monkeypatch.chdir(tmp_path)

        messages: list[str] = []
        monkeypatch.setattr(
            merge_worktree,
            "_print",
            lambda msg="", err=False: messages.append(msg),
        )

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"))
        ctx.repo_root = str(repo)

        result = merge_worktree.check_and_clean_root_dirty_state(ctx)
        assert result is None

        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""

        last_subject = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "auto-commit Yoke bookkeeping before merge [YOK-9999]" in last_subject.stdout
        assert any("Auto-committed Yoke bookkeeping files." in message for message in messages)


# ---------------------------------------------------------------------------
# Merge lock integration tests
# ---------------------------------------------------------------------------


class TestMergeLockIntegration:
    def test_check_no_locks(self, mw_db):
        from yoke_core.domain import merge_lock
        msg = merge_lock.check(mw_db["conn"])
        assert msg is None

    def test_acquire_and_release(self, mw_db):
        from yoke_core.domain import merge_lock
        handle = merge_lock.acquire("YOK-9999", conn=mw_db["conn"])
        assert handle.session_id
        assert handle.branch == "YOK-9999"

        # Should be blocked now (our own PID is alive)
        msg = merge_lock.check(mw_db["conn"])
        assert msg is not None
        assert "YOK-9999" in msg

        # Release
        merge_lock.release(handle, conn=mw_db["conn"])
        msg = merge_lock.check(mw_db["conn"])
        assert msg is None

    def test_force_clear(self, mw_db):
        from yoke_core.domain import merge_lock
        merge_lock.acquire("YOK-9999", conn=mw_db["conn"])
        merge_lock.acquire("YOK-43", conn=mw_db["conn"])
        merge_lock.force_clear(mw_db["conn"])
        msg = merge_lock.check(mw_db["conn"])
        assert msg is None

    def test_acquire_with_epic(self, mw_db):
        from yoke_core.domain import merge_lock
        handle = merge_lock.acquire("YOK-9999", epic_id="100", conn=mw_db["conn"])
        msg = merge_lock.check(mw_db["conn"])
        assert msg is not None
        assert "epic: 100" in msg
        merge_lock.release(handle, conn=mw_db["conn"])

    def test_stale_pid_auto_cleanup(self, mw_db):
        """Locks from dead PIDs are automatically cleaned."""
        from yoke_core.domain import merge_lock
        conn = mw_db["conn"]
        # Insert a lock row with a PID that doesn't exist
        conn.execute(
            "INSERT INTO merge_locks (session_id, branch, acquired_at, expires_at) "
            "VALUES ('999999-1000000', 'YOK-99', '2030-01-01T00:00:00Z', '2030-01-01T01:00:00Z')"
        )
        conn.commit()

        # Check should auto-clean it (PID 999999 is almost certainly dead)
        msg = merge_lock.check(conn)
        assert msg is None

        # Verify row was deleted
        count = conn.execute("SELECT COUNT(*) FROM merge_locks").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# Generated file extraction tests
# ---------------------------------------------------------------------------


class TestExtractGeneratedFiles:
    def test_no_epic(self, mw_db):
        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"), epic_id=None)
        assert extract_generated_files(ctx) == []

    def test_epic_with_generated_files(self, mw_db):
        conn = mw_db["conn"]
        body = (
            "## Worktree: YOK-9999\n"
            "Generated files\n"
            "- dist/bundle.js\n"
            "- dist/styles.css\n"
            "## Worktree: YOK-43\n"
        )
        p = _p(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, spec, project_id, project_sequence, "
            "created_at, updated_at) "
            f"VALUES (100, 'Test Epic', 'epic', 'implementing', {p}, 1, 100, "
            "'2025-01-01', '2025-01-01')",
            (body,),
        )
        conn.commit()

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"), epic_id="100")
        files = extract_generated_files(ctx)
        assert "dist/bundle.js" in files
        assert "dist/styles.css" in files

    def test_wrong_branch_section(self, mw_db):
        conn = mw_db["conn"]
        body = (
            "## Worktree: YOK-99\n"
            "Generated files\n"
            "- dist/bundle.js\n"
        )
        p = _p(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, spec, project_id, project_sequence, "
            "created_at, updated_at) "
            f"VALUES (100, 'Test', 'epic', 'implementing', {p}, 1, 100, "
            "'2025-01-01', '2025-01-01')",
            (body,),
        )
        conn.commit()

        ctx = MergeContext(args=MergeArgs(branch="YOK-9999"), epic_id="100")
        files = extract_generated_files(ctx)
        assert files == []


# ---------------------------------------------------------------------------
# Preflight: epic task completeness
# ---------------------------------------------------------------------------


class TestPreflightEpicTasks:
    def test_all_tasks_complete(self, mw_db):
        conn = mw_db["conn"]
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 1, 'done')")
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 2, 'reviewed-implementation')")
        conn.commit()

        # Direct DB check matching preflight logic
        terminal_list = merge_worktree._sql_task_terminal_success_list()
        incomplete = conn.execute(
            f"SELECT task_num, status FROM epic_tasks "
            f"WHERE epic_id='100' AND status NOT IN ({terminal_list}) "
            f"ORDER BY task_num"
        ).fetchall()
        assert len(incomplete) == 0

    def test_incomplete_tasks(self, mw_db):
        conn = mw_db["conn"]
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 1, 'done')")
        conn.execute("INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 2, 'implementing')")
        conn.commit()

        terminal_list = merge_worktree._sql_task_terminal_success_list()
        incomplete = conn.execute(
            f"SELECT task_num, status FROM epic_tasks "
            f"WHERE epic_id='100' AND status NOT IN ({terminal_list}) "
            f"ORDER BY task_num"
        ).fetchall()
        assert len(incomplete) == 1
        assert incomplete[0][0] == 2


# ---------------------------------------------------------------------------
# Merge lock CLI tests
# ---------------------------------------------------------------------------


class TestMergeLockCLI:
    def test_check_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main
        result = lock_main(["check"])
        assert result == 0

    def test_acquire_release_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main
        # Capture session_id from acquire
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            result = lock_main(["acquire", "YOK-9999"])
        assert result == 0
        session_id = f.getvalue().strip()
        assert session_id

        # Now release it
        result = lock_main(["release", session_id, "YOK-9999"])
        assert result == 0

    def test_force_clear_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main
        result = lock_main(["force-clear"])
        assert result == 0

    def test_unknown_command(self, mw_db):
        from yoke_core.domain.merge_lock import main as lock_main
        result = lock_main(["bogus"])
        assert result == 2


# ---------------------------------------------------------------------------
# Glob matching tests
# ---------------------------------------------------------------------------


class TestGlobMatching:
    def test_matches_exact(self):
        assert merge_worktree._matches_glob(".yoke/BOARD.md", [".yoke/BOARD.md"]) is True

    def test_matches_wildcard(self):
        assert merge_worktree._matches_glob(".yoke/backups/042.md", [".yoke/backups/*"]) is True

    def test_no_match(self):
        assert merge_worktree._matches_glob("src/app.js", [".yoke/backups/*"]) is False


# ---------------------------------------------------------------------------
# root resolution and post-merge-cleanup exit-code class
#
# These tests guard the three-way path taxonomy in merge_worktree:
#   - ctx.repo_root              : project repo (may be non-yoke)
#   - ctx.yoke_repo_root       : Yoke control-repo root (YOKE_REPO_ROOT)
#   - _yoke_state_dir(ctx)     : <control-repo>/.yoke (artifact dir)
#
# The 2026-04-11 incident was caused by _regenerate_views() treating
# ctx.yoke_repo_root itself as the state dir and computing
# ``<control-repo>/backlog`` instead of ``<control-repo>/yoke/backlog``.
# ---------------------------------------------------------------------------
