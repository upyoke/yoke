"""Resolve registered worktree lanes by complete public item identity."""

import os
import subprocess
from unittest.mock import patch

import pytest

from runtime.api.domain.test_worktree_create import _seed_item, _seed_project_repo
from runtime.api.domain.worktree_test_helpers import TEST_ITEM_ID, TEST_ITEM_REF
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.worktree import resolve_item_worktree


class TestResolveItemWorktree:
    def test_existing_worktree(self, git_repo, yoke_db):
        # Set up DB
        conn = connect_test_db(yoke_db)
        _seed_item(conn, TEST_ITEM_ID, worktree=TEST_ITEM_REF)
        _seed_project_repo(conn, "yoke", str(git_repo))
        conn.commit()
        conn.close()

        # Create actual worktree
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                str(git_repo / ".worktrees" / TEST_ITEM_REF),
                "-b",
                TEST_ITEM_REF,
                "main",
            ],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )

        with patch.dict(os.environ, {"YOKE_ROOT": str(git_repo)}):
            result = resolve_item_worktree(TEST_ITEM_REF, db_path=yoke_db)

        assert result.exists is True
        assert result.branch == TEST_ITEM_REF
        assert result.project == "yoke"
        assert result.path.endswith(f".worktrees/{TEST_ITEM_REF}")

    def test_unrecorded_item_has_no_resolved_lane(self, git_repo, yoke_db):
        conn = connect_test_db(yoke_db)
        _seed_item(conn, 43, worktree="")
        _seed_project_repo(conn, "yoke", str(git_repo))
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"YOKE_ROOT": str(git_repo)}):
            result = resolve_item_worktree("YOK-43", db_path=yoke_db)

        assert result.branch == ""
        assert result.path == ""
        assert result.exists is False

    def test_external_project(self, tmp_path, yoke_db):
        # Create external repo
        ext_repo = tmp_path / "externalwebapp"
        ext_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(ext_repo), check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t"], cwd=str(ext_repo), check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "T"], cwd=str(ext_repo), check=True
        )
        subprocess.run(
            ["git", "checkout", "-qb", "main"],
            cwd=str(ext_repo),
            check=True,
            capture_output=True,
        )
        (ext_repo / "README.md").write_text("externalwebapp\n")
        subprocess.run(["git", "add", "README.md"], cwd=str(ext_repo), check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"],
            cwd=str(ext_repo),
            check=True,
            capture_output=True,
        )

        (ext_repo / "runtime").mkdir()
        (ext_repo / "runtime" / "config").write_text("worktrees_dir=.worktrees\n")

        # Create worktree in ext repo
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                str(ext_repo / ".worktrees" / "YOK-77"),
                "-b",
                "YOK-77",
                "main",
            ],
            cwd=str(ext_repo),
            check=True,
            capture_output=True,
        )

        conn = connect_test_db(yoke_db)
        _seed_item(conn, 77, title="Ext", worktree="YOK-77", project="externalwebapp")
        _seed_project_repo(conn, "externalwebapp", str(ext_repo))
        conn.commit()
        conn.close()

        result = resolve_item_worktree("EXT-77", db_path=yoke_db)

        assert result.project == "externalwebapp"
        assert result.exists is True
        assert str(ext_repo) in result.repo

    def test_missing_item(self, yoke_db):
        with pytest.raises(LookupError, match="not found"):
            resolve_item_worktree(999, db_path=yoke_db)

    def test_invalid_id(self):
        with pytest.raises(ValueError, match="public_item_ref_required"):
            resolve_item_worktree("abc")

    def test_live_branch_override(self, git_repo, yoke_db):
        """When the checked-out branch differs from the lane record, live wins."""
        conn = connect_test_db(yoke_db)
        _seed_item(
            conn,
            44,
            worktree="stale-branch-name",
            worktree_path=str(git_repo / ".worktrees" / "YOK-44"),
        )
        _seed_project_repo(conn, "yoke", str(git_repo))
        conn.commit()
        conn.close()

        # Create worktree with a different branch name
        subprocess.run(
            [
                "git",
                "worktree",
                "add",
                str(git_repo / ".worktrees" / "YOK-44"),
                "-b",
                "renamed-yok-44",
                "main",
            ],
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )

        with patch.dict(os.environ, {"YOKE_ROOT": str(git_repo)}):
            result = resolve_item_worktree("YOK-44", db_path=yoke_db)

        assert result.branch == "renamed-yok-44"
        assert result.exists is True
