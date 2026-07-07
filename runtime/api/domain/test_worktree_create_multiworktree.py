"""Multi-worktree coverage for the unified ``create_worktree``."""

from __future__ import annotations

import os
import subprocess
import sys

from yoke_core.domain import db_backend
from yoke_core.domain import worktree as worktree_cli
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.worktree import create_worktree
from yoke_core.domain.worktree_test_helpers import (  # noqa: F401 — fixtures
    git_repo,
    yoke_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def seed_multiworktree_epic(db_path: str, epic_id: int, branches, repo_root: str):
    """Seed an ``items`` row + ``epic_dispatch_chains`` rows for *branches*.

    Returns the ordered ``(branch, worktree_path)`` list the unified
    creator should iterate over.
    """
    conn = connect_test_db(db_path)
    execute_schema_script(conn, """\
        CREATE TABLE IF NOT EXISTS epic_dispatch_chains (
            id INTEGER PRIMARY KEY,
            epic_id INTEGER NOT NULL,
            worktree TEXT NOT NULL,
            worktree_path TEXT,
            queue TEXT,
            current_index INTEGER DEFAULT 0,
            current_task TEXT,
            current_attempt INTEGER DEFAULT 1,
            max_attempts INTEGER DEFAULT 5,
            no_chain INTEGER DEFAULT 0,
            started_at TEXT,
            last_updated TEXT,
            UNIQUE(epic_id, worktree)
        );
    """)
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, project_id, project_sequence) "
        f"VALUES ({p}, 'Multi-worktree epic', 'epic', 'implementing', {p}, {p}) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
        "type=excluded.type, status=excluded.status, "
        "project_id=excluded.project_id, project_sequence=excluded.project_sequence",
        (epic_id, 1, epic_id),
    )
    entries = []
    for branch in branches:
        wt_path = os.path.join(repo_root, ".worktrees", branch)
        conn.execute(
            "INSERT INTO epic_dispatch_chains "
            f"(epic_id, worktree, worktree_path, queue) VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(epic_id, worktree) DO UPDATE SET "
            "worktree_path=excluded.worktree_path, queue=excluded.queue",
            (epic_id, branch, wt_path, "[]"),
        )
        entries.append((branch, wt_path))
    conn.commit()
    conn.close()
    return entries


def _config_path(git_repo) -> str:
    return str(git_repo / "runtime" / "config")


class TestCreateWorktreeMultiWorktree:
    def test_single_worktree_unchanged_when_no_epic_chains(self, git_repo, yoke_db):
        # Single-worktree (issue) item still creates one worktree at YOK-{N}.
        conn = connect_test_db(yoke_db)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, project_id, project_sequence) "
            "VALUES (99100, 'plain issue', 'issue', 'implementing', 1, 99100)",
        )
        conn.commit()
        conn.close()

        result = create_worktree(
            99100, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is None
        assert result.created is True
        assert result.branch == "YOK-99100"
        assert result.path.endswith(".worktrees/YOK-99100")
        assert len(result.worktrees) == 1
        assert result.worktrees[0].branch == "YOK-99100"
        assert result.worktrees[0].created is True

    def test_multi_worktree_epic_creates_one_per_chain(self, git_repo, yoke_db):
        # Epic with N>=2 chains produces N worktrees, one per chain row.
        # Worktree order follows ``epic_dispatch_chains.worktree`` (alphabetical),
        # matching the pre-existing ``resolve_item_worktree`` contract.
        branches = ["epic-99200-cli", "epic-99200-core", "epic-99200-tests"]
        entries = seed_multiworktree_epic(yoke_db, 99200, branches, str(git_repo))

        result = create_worktree(
            99200, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is None, result.error
        assert result.created is True
        assert len(result.worktrees) == len(branches)
        assert sorted(entry.branch for entry in result.worktrees) == sorted(branches)
        assert sorted(entry.path for entry in result.worktrees) == sorted(
            path for _, path in entries
        )
        for branch, path in entries:
            assert os.path.isdir(path), f"missing worktree at {path}"
            cur = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=path, capture_output=True, text=True,
            )
            assert cur.stdout.strip() == branch

        # Git worktree list includes one entry per chain.
        listing = subprocess.run(
            ["git", "-C", str(git_repo), "worktree", "list", "--porcelain"],
            capture_output=True, text=True,
        )
        for _, path in entries:
            assert path in listing.stdout

    def test_multi_worktree_idempotency_skips_existing(self, git_repo, yoke_db):
        # Rerunning is a no-op for worktrees already on the expected branch.
        branches = ["epic-99201-a", "epic-99201-b"]
        seed_multiworktree_epic(yoke_db, 99201, branches, str(git_repo))
        first = create_worktree(
            99201, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )
        assert first.error is None and first.created is True

        second = create_worktree(
            99201, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert second.error is None
        assert second.created is False
        assert all(entry.preexisting for entry in second.worktrees)
        assert [entry.path for entry in second.worktrees] == [
            entry.path for entry in first.worktrees
        ]

    def test_multi_worktree_creation_does_not_race_a_session_envelope(
        self, git_repo, yoke_db,
    ):
        # Parallel multi-worktree creation does not race a single session
        # envelope, because the envelope is gone. Per-worktree authority comes
        # from each subagent's work_claim on the parent epic, validated
        # per call by lint_session_cwd. Each worktree stands on its own.
        branches = ["epic-99202-aaa", "epic-99202-bbb", "epic-99202-ccc"]
        entries = seed_multiworktree_epic(yoke_db, 99202, branches, str(git_repo))

        result = create_worktree(
            99202, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is None
        # The result no longer carries scope_entered / scope_message fields.
        assert not hasattr(result, "scope_entered")
        assert not hasattr(result, "scope_message")
        # Primary worktree is the first chain in epic_dispatch_chains.worktree order.
        primary_branch, primary_path = entries[0]
        assert result.branch == primary_branch
        assert result.path == primary_path
        # All sibling worktrees provisioned (parallel-fan-out shape; no envelope
        # race because there is no envelope).
        assert len(result.worktrees) == len(entries)
        for wt_result, (expected_branch, expected_path) in zip(result.worktrees, entries):
            assert wt_result.branch == expected_branch
            assert wt_result.path == expected_path
            assert os.path.isdir(expected_path)

    def test_preflight_blocks_before_side_effects(self, git_repo, yoke_db):
        # Capacity check fails the entire call before any
        # `git worktree add` runs for any worktree.
        cfg = git_repo / "runtime" / "config"
        cfg.write_text("worktrees_dir=.worktrees\nmax_active_worktrees=1\n")
        branches = ["epic-99203-x", "epic-99203-y"]
        seed_multiworktree_epic(yoke_db, 99203, branches, str(git_repo))

        result = create_worktree(
            99203, repo_root=str(git_repo), config_path=str(cfg),
            db_path=yoke_db,
        )

        assert result.error is not None
        assert "max_active_worktrees" in result.error
        # No worktree directories created — all-worktree preflight blocked first.
        for branch in branches:
            assert not os.path.isdir(str(git_repo / ".worktrees" / branch))

    def test_duplicate_worktree_path_blocks_before_side_effects(self, git_repo, yoke_db):
        branches = ["epic-99209-a", "epic-99209-b"]
        entries = seed_multiworktree_epic(yoke_db, 99209, branches, str(git_repo))
        conn = connect_test_db(yoke_db)
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE epic_dispatch_chains SET worktree_path = {p} "
            f"WHERE epic_id = {p} AND worktree = {p}",
            (entries[0][1], 99209, branches[1]),
        )
        conn.commit()
        conn.close()

        result = create_worktree(
            99209, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is not None
        assert "duplicate worktree path" in result.error
        assert not os.path.isdir(entries[0][1])

    def test_dirty_main_blocks_before_side_effects(self, git_repo, yoke_db):
        branches = ["epic-99210-a", "epic-99210-b"]
        entries = seed_multiworktree_epic(yoke_db, 99210, branches, str(git_repo))
        (git_repo / "dirty.txt").write_text("dirty\n")

        result = create_worktree(
            99210, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is not None
        assert "main has untracked" in result.error
        for _, path in entries:
            assert not os.path.isdir(path)

    def test_mismatched_existing_branch_blocks(self, git_repo, yoke_db):
        # Existing-dir on wrong branch returns structured error, no partial state.
        branches = ["epic-99204-good", "epic-99204-clash"]
        entries = seed_multiworktree_epic(yoke_db, 99204, branches, str(git_repo))
        # Pre-create the second worktree's path on a DIFFERENT branch.
        clash_path = entries[1][1]
        subprocess.run(
            ["git", "worktree", "add", clash_path, "-b", "wrong-branch", "main"],
            cwd=str(git_repo), check=True, capture_output=True,
        )

        result = create_worktree(
            99204, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is not None
        assert "epic-99204-clash" in result.error
        # First worktree's directory MUST NOT have been created — preflight halts
        # before side effects.
        assert not os.path.isdir(entries[0][1])

    def test_result_backward_compat_for_single_worktree(self, git_repo):
        # Existing single-worktree callers receive populated path/branch/created.
        result = create_worktree(
            99205, repo_root=str(git_repo), config_path=_config_path(git_repo),
        )
        assert result.path.endswith(".worktrees/YOK-99205")
        assert result.branch == "YOK-99205"
        assert result.created is True
        # `worktrees` is present but len()==1 for single-worktree.
        assert len(result.worktrees) == 1

    def test_main_create_prints_one_path_per_worktree(
        self, git_repo, yoke_db, monkeypatch, capsys,
    ):
        # CLI prints one path per worktree for multi-worktree items.
        # ``main_create`` always passes ``repo_root=None`` (env-resolved),
        # so the patched create must override that None back to git_repo.
        branches = ["epic-99206-aaa", "epic-99206-bbb"]
        entries = seed_multiworktree_epic(yoke_db, 99206, branches, str(git_repo))
        original = worktree_cli.create_worktree

        def patched_create(item_num, **kwargs):
            if kwargs.get("repo_root") is None:
                kwargs["repo_root"] = str(git_repo)
            if kwargs.get("config_path") is None:
                kwargs["config_path"] = _config_path(git_repo)
            if kwargs.get("db_path") is None:
                kwargs["db_path"] = yoke_db
            return original(item_num, **kwargs)

        monkeypatch.setattr(worktree_cli, "create_worktree", patched_create)
        monkeypatch.setattr(sys, "argv", ["worktree", "create", "99206"])

        rc = worktree_cli.main_create()
        assert rc == 0, capsys.readouterr().err
        out = capsys.readouterr().out.strip().splitlines()
        assert sorted(out) == sorted(path for _, path in entries)

    def test_main_create_prints_single_path_for_issue(
        self, git_repo, monkeypatch, capsys,
    ):
        # Single-worktree callers still see one path on stdout (no change).
        original = worktree_cli.create_worktree

        def patched_create(item_num, **kwargs):
            if kwargs.get("repo_root") is None:
                kwargs["repo_root"] = str(git_repo)
            if kwargs.get("config_path") is None:
                kwargs["config_path"] = _config_path(git_repo)
            return original(item_num, **kwargs)

        monkeypatch.setattr(worktree_cli, "create_worktree", patched_create)
        monkeypatch.setattr(sys, "argv", ["worktree", "create", "99207"])

        rc = worktree_cli.main_create()
        assert rc == 0, capsys.readouterr().err
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1
        assert out[0].endswith(".worktrees/YOK-99207")

    def test_falls_back_to_single_worktree_when_no_chains(self, git_repo, yoke_db):
        # AC-2 edge: epic item with NO chains falls back to single-worktree shape.
        conn = connect_test_db(yoke_db)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, project_id, project_sequence) "
            "VALUES (99208, 'empty epic', 'epic', 'implementing', 1, 99208)",
        )
        conn.commit()
        conn.close()

        result = create_worktree(
            99208, repo_root=str(git_repo), config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is None
        assert result.created is True
        assert len(result.worktrees) == 1
        assert result.worktrees[0].branch == "YOK-99208"
