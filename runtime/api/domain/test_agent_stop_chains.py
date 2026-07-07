"""agent_stop — process_dispatch_chains coverage."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.agent_stop import process_dispatch_chains
from yoke_core.domain.agent_stop_test_helpers import _init_git_repo


_UNUSED_DB_NAME = "unused.db"


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
        assert ctx.dispatch_type == "issue"

    def test_issue_basename_triggers_auto_commit(self, tmp_path: Path):
        """When ``agent_dir`` basename is ``YOK-<num>`` and differs from
        ``project_root``, dirty worktree work is auto-committed and the
        item id is captured on the context.
        """
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = tmp_path / "YOK-42"
        wt.mkdir()
        _init_git_repo(wt)
        (wt / "dirty.txt").write_text("dirty\n")

        ctx = process_dispatch_chains(
            db_path=str(tmp_path / _UNUSED_DB_NAME),
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == "42"
        assert ctx.auto_committed is True
        assert ctx.auto_commit_file_count == 1

    def test_issue_basename_clean_worktree_no_commit(self, tmp_path: Path):
        """Clean YOK-named worktree records item_id but does not commit."""
        project_root = tmp_path / "repo"
        project_root.mkdir()
        wt = tmp_path / "YOK-42"
        wt.mkdir()
        _init_git_repo(wt)

        ctx = process_dispatch_chains(
            db_path=str(tmp_path / _UNUSED_DB_NAME),
            script_dir=str(tmp_path / "scripts"),
            project_root=str(project_root),
            agent_dir=str(wt),
            session_id="sess-1",
        )

        assert ctx.item_id == "42"
        assert ctx.auto_committed is False
