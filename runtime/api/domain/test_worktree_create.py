"""worktree — create_worktree + resolve_item_worktree integration coverage.

Split out of ``test_worktree.py`` to keep authored files under the 350-line
limit. Multi-worktree creator coverage lives in
``test_worktree_create_multiworktree.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.worktree import (
    create_worktree,
    resolve_item_worktree,
)
from yoke_core.domain.worktree_test_helpers import (  # noqa: F401 — fixtures
    TEST_ITEM_ID,
    TEST_ITEM_REF,
    git_repo,
    yoke_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(slug: str = "yoke") -> int:
    return SEED_PROJECT_IDS[slug]


def _seed_project_repo(conn, slug: str, repo_path: str) -> None:
    repo = Path(repo_path)
    register_machine_checkout(
        repo.parent / "machine-config", repo, _project_id(slug)
    )


def _seed_item(
    conn,
    item_id: int,
    *,
    title: str = "Test",
    status: str = "implementing",
    worktree=None,
    project: str = "yoke",
    item_type: str = "issue",
) -> None:
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, worktree, project_id, project_sequence) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (
            item_id,
            title,
            item_type,
            status,
            worktree,
            _project_id(project),
            item_id,
        ),
    )


class TestCreateWorktree:
    def test_basic_creation(self, git_repo):
        result = create_worktree(
            TEST_ITEM_ID, repo_root=str(git_repo),
            config_path=str(git_repo / "runtime" / "config"),
        )
        assert result.error is None
        assert result.created is True
        assert result.branch == TEST_ITEM_REF
        assert os.path.isdir(result.path)
        assert result.path.endswith(f".worktrees/{TEST_ITEM_REF}")

        # Verify it's a real git worktree
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=result.path, capture_output=True, text=True,
        )
        assert r.stdout.strip() == "true"

        # Verify branch name
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=result.path, capture_output=True, text=True,
        )
        assert r.stdout.strip() == TEST_ITEM_REF

    def test_create_does_not_bind_session_scope(self, git_repo):
        # Worktree creation no longer binds a session-scope envelope.
        # The session's authority over the new worktree comes from its
        # active work_claims, validated per call by lint_session_cwd.
        result = create_worktree(
            50,
            repo_root=str(git_repo),
            config_path=str(git_repo / "runtime" / "config"),
        )

        assert result.error is None
        assert result.created is True
        # The result no longer carries scope_entered / scope_message fields.
        assert not hasattr(result, "scope_entered")
        assert not hasattr(result, "scope_message")

    def test_idempotency(self, git_repo):
        result1 = create_worktree(42, repo_root=str(git_repo),
                                   config_path=str(git_repo / "runtime" / "config"))
        result2 = create_worktree(42, repo_root=str(git_repo),
                                   config_path=str(git_repo / "runtime" / "config"))
        assert result2.error is None
        assert result2.created is False
        assert result2.path == result1.path

    def test_base_branch_override(self, git_repo):
        # Create a feature branch to fork from
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(git_repo),
                        check=True, capture_output=True)
        (git_repo / "feature.txt").write_text("feature\n")
        subprocess.run(["git", "add", "feature.txt"], cwd=str(git_repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feature"],
                        cwd=str(git_repo), check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=str(git_repo),
                        check=True, capture_output=True)

        result = create_worktree(
            99, base_branch="feature", repo_root=str(git_repo),
            config_path=str(git_repo / "runtime" / "config"),
        )
        assert result.error is None
        assert result.created is True

        # Verify the worktree has the feature file
        assert os.path.isfile(os.path.join(result.path, "feature.txt"))

    def test_guardrail(self, git_repo):
        cfg = git_repo / "runtime" / "config"
        cfg.write_text("worktrees_dir=.worktrees\nmax_active_worktrees=2\n")
        config_path = str(cfg)

        create_worktree(1, repo_root=str(git_repo), config_path=config_path)
        create_worktree(2, repo_root=str(git_repo), config_path=config_path)
        result = create_worktree(3, repo_root=str(git_repo), config_path=config_path)

        assert result.error is not None
        assert "max_active_worktrees" in result.error
        assert result.created is False

    def test_nonexistent_repo(self, tmp_path):
        """Worktree creation fails gracefully when repo doesn't exist."""
        fake_repo = str(tmp_path / "nonexistent")
        result = create_worktree(
            99, repo_root=fake_repo,
            config_path=str(tmp_path / "config"),
        )
        assert result.error is not None or not result.created

    def test_persists_items_worktree_without_explicit_db_path(
        self, git_repo, yoke_db,
    ):
        # The preflight caller never threads db_path through; without the
        # YOKE_DB-driven fallback in _persist_item_worktree the write
        # silently no-ops and every Edit/Write in the new worktree is
        # refused by lint_session_cwd.
        conn = connect_test_db(yoke_db)
        _seed_item(conn, TEST_ITEM_ID, worktree=None)
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"YOKE_DB": yoke_db}):
            result = create_worktree(
                TEST_ITEM_ID,
                repo_root=str(git_repo),
                config_path=str(git_repo / "runtime" / "config"),
            )

        assert result.error is None
        assert result.created is True

        conn = connect_test_db(yoke_db)
        p = _placeholder(conn)
        row = conn.execute(
            f"SELECT worktree FROM items WHERE id = {p}", (TEST_ITEM_ID,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == TEST_ITEM_REF


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
            ["git", "worktree", "add", str(git_repo / ".worktrees" / TEST_ITEM_REF), "-b", TEST_ITEM_REF, "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )

        with patch.dict(os.environ, {"YOKE_ROOT": str(git_repo)}):
            result = resolve_item_worktree(TEST_ITEM_REF, db_path=yoke_db)

        assert result.exists is True
        assert result.branch == TEST_ITEM_REF
        assert result.project == "yoke"
        assert result.path.endswith(f".worktrees/{TEST_ITEM_REF}")

    def test_fallback_branch(self, git_repo, yoke_db):
        conn = connect_test_db(yoke_db)
        _seed_item(conn, 43, worktree="")
        _seed_project_repo(conn, "yoke", str(git_repo))
        conn.commit()
        conn.close()

        with patch.dict(os.environ, {"YOKE_ROOT": str(git_repo)}):
            result = resolve_item_worktree("YOK-43", db_path=yoke_db)

        assert result.branch == "YOK-43"
        assert result.exists is False

    def test_external_project(self, tmp_path, yoke_db):
        # Create external repo
        ext_repo = tmp_path / "buzz"
        ext_repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(ext_repo), check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(ext_repo), check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(ext_repo), check=True)
        subprocess.run(["git", "checkout", "-qb", "main"], cwd=str(ext_repo),
                        check=True, capture_output=True)
        (ext_repo / "README.md").write_text("buzz\n")
        subprocess.run(["git", "add", "README.md"], cwd=str(ext_repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"],
                        cwd=str(ext_repo), check=True, capture_output=True)

        (ext_repo / "runtime").mkdir()
        (ext_repo / "runtime" / "config").write_text("worktrees_dir=.worktrees\n")

        # Create worktree in ext repo
        subprocess.run(
            ["git", "worktree", "add", str(ext_repo / ".worktrees" / "YOK-77"), "-b", "YOK-77", "main"],
            cwd=str(ext_repo), check=True, capture_output=True,
        )

        conn = connect_test_db(yoke_db)
        _seed_item(conn, 77, title="Ext", worktree="YOK-77", project="buzz")
        _seed_project_repo(conn, "buzz", str(ext_repo))
        conn.commit()
        conn.close()

        result = resolve_item_worktree("YOK-77", db_path=yoke_db)

        assert result.project == "buzz"
        assert result.exists is True
        assert str(ext_repo) in result.repo

    def test_missing_item(self, yoke_db):
        with pytest.raises(LookupError, match="not found"):
            resolve_item_worktree("YOK-999", db_path=yoke_db)

    def test_invalid_id(self):
        with pytest.raises(ValueError, match="invalid"):
            resolve_item_worktree("abc")

    def test_live_branch_override(self, git_repo, yoke_db):
        """When actual branch differs from DB worktree field, live branch wins."""
        conn = connect_test_db(yoke_db)
        _seed_item(conn, 44, worktree="stale-branch-name")
        _seed_project_repo(conn, "yoke", str(git_repo))
        conn.commit()
        conn.close()

        # Create worktree with a different branch name
        subprocess.run(
            ["git", "worktree", "add", str(git_repo / ".worktrees" / "YOK-44"), "-b", "renamed-yok-44", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )

        with patch.dict(os.environ, {"YOKE_ROOT": str(git_repo)}):
            result = resolve_item_worktree("YOK-44", db_path=yoke_db)

        assert result.branch == "renamed-yok-44"
        assert result.exists is True
