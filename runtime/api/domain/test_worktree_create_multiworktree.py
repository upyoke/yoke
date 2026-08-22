"""Multi-worktree coverage for the unified ``create_worktree``."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import worktree as worktree_cli
from yoke_core.domain import yok_n_parser
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain.worktree import create_worktree
from runtime.api.domain.worktree_test_helpers import pin_test_item_workflow
from runtime.api.fixtures.file_test_db import connect_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def seed_multiworktree_epic(db_path: str, epic_id: int, branches, repo_root: str):
    """Seed an item plus universal worker lanes for *branches*.

    Returns the ordered ``(branch, worktree_path)`` list the unified
    creator should iterate over.
    """
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, project_id, project_sequence) "
        f"VALUES ({p}, 'Multi-worktree epic', 'implementing', {p}, {p}) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
        "status=excluded.status, "
        "project_id=excluded.project_id, project_sequence=excluded.project_sequence",
        (epic_id, 1, epic_id),
    )
    pin_test_item_workflow(conn, epic_id, "epic")
    entries = []
    for branch in branches:
        wt_path = os.path.join(repo_root, ".worktrees", branch)
        lane = record_item_worktree(
            conn,
            item_id=epic_id,
            branch=branch,
            path=wt_path,
            lane_role="worker",
        )
        conn.execute(
            "INSERT INTO epic_dispatch_chains "
            f"(epic_id, item_worktree_id, queue) VALUES ({p}, {p}, {p}) "
            "ON CONFLICT(epic_id, item_worktree_id) DO UPDATE SET "
            "queue=excluded.queue",
            (epic_id, lane["id"], "[]"),
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
            "(id, title, status, project_id, project_sequence) "
            "VALUES (99100, 'plain issue', 'implementing', 1, 99100)",
        )
        pin_test_item_workflow(conn, 99100, "issue")
        conn.commit()
        conn.close()

        result = create_worktree(
            99100,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is None
        assert result.created is True
        assert result.branch == "YOK-99100"
        assert result.path.endswith(".worktrees/YOK-99100")
        assert len(result.worktrees) == 1
        assert result.worktrees[0].branch == "YOK-99100"
        assert result.worktrees[0].created is True

    def test_multi_worktree_idempotency_skips_existing(self, git_repo, yoke_db):
        # Rerunning is a no-op for worktrees already on the expected branch.
        branches = ["epic-99201-a", "epic-99201-b"]
        seed_multiworktree_epic(yoke_db, 99201, branches, str(git_repo))
        first = create_worktree(
            99201,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
            db_path=yoke_db,
        )
        assert first.error is None and first.created is True

        second = create_worktree(
            99201,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert second.error is None
        assert second.created is False
        assert all(entry.preexisting for entry in second.worktrees)
        assert [entry.path for entry in second.worktrees] == [
            entry.path for entry in first.worktrees
        ]

    def test_multi_worktree_creation_does_not_race_a_session_envelope(
        self,
        git_repo,
        yoke_db,
    ):
        branches = ["epic-99202-aaa", "epic-99202-bbb", "epic-99202-ccc"]
        entries = seed_multiworktree_epic(yoke_db, 99202, branches, str(git_repo))

        result = create_worktree(
            99202,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error is None
        assert not hasattr(result, "scope_entered")
        assert not hasattr(result, "scope_message")
        assert result.branch == "YOK-99202"
        assert result.path.endswith(".worktrees/YOK-99202")
        assert len(result.worktrees) == len(entries) + 1
        for wt_result, (expected_branch, expected_path) in zip(
            result.worktrees[1:],
            entries,
        ):
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
            99203,
            repo_root=str(git_repo),
            config_path=str(cfg),
            db_path=yoke_db,
        )

        assert result.error is not None
        assert "max_active_worktrees" in result.error
        # No worktree directories created — all-worktree preflight blocked first.
        for branch in branches:
            assert not os.path.isdir(str(git_repo / ".worktrees" / branch))

    def test_duplicate_worktree_path_is_rejected_by_registry(
        self, git_repo, yoke_db
    ):
        branches = ["epic-99209-a", "epic-99209-b"]
        entries = seed_multiworktree_epic(yoke_db, 99209, branches, str(git_repo))
        conn = connect_test_db(yoke_db)
        p = _placeholder(conn)
        with pytest.raises(db_backend.integrity_error_types(conn)):
            conn.execute(
                f"UPDATE item_worktrees SET path = {p} "
                f"WHERE item_id = {p} AND branch = {p}",
                (entries[0][1], 99209, branches[1]),
            )
        conn.close()
        assert not os.path.isdir(entries[0][1])

    def test_dirty_main_blocks_before_side_effects(self, git_repo, yoke_db):
        branches = ["epic-99210-a", "epic-99210-b"]
        entries = seed_multiworktree_epic(yoke_db, 99210, branches, str(git_repo))
        (git_repo / "dirty.txt").write_text("dirty\n")

        result = create_worktree(
            99210,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
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
            cwd=str(git_repo),
            check=True,
            capture_output=True,
        )

        result = create_worktree(
            99204,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
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
            99205,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
        )
        assert result.path.endswith(".worktrees/YOK-99205")
        assert result.branch == "YOK-99205"
        assert result.created is True
        # `worktrees` is present but len()==1 for single-worktree.
        assert len(result.worktrees) == 1

    def test_main_create_prints_one_path_per_worktree(
        self,
        git_repo,
        yoke_db,
        monkeypatch,
        capsys,
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
        monkeypatch.setattr(
            yok_n_parser,
            "parse_item_argument",
            lambda *_args, **_kwargs: 99206,
        )
        monkeypatch.setattr(sys, "argv", ["worktree", "create", "YOK-99206"])

        rc = worktree_cli.main_create()
        assert rc == 0, capsys.readouterr().err
        out = capsys.readouterr().out.strip().splitlines()
        expected = [
            str(git_repo / ".worktrees" / "YOK-99206"),
            *(path for _, path in entries),
        ]
        assert sorted(out) == sorted(expected)

    def test_main_create_prints_single_path_for_issue(
        self,
        git_repo,
        monkeypatch,
        capsys,
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
        monkeypatch.setattr(
            yok_n_parser,
            "parse_item_argument",
            lambda *_args, **_kwargs: 99207,
        )
        monkeypatch.setattr(sys, "argv", ["worktree", "create", "YOK-99207"])

        rc = worktree_cli.main_create()
        assert rc == 0, capsys.readouterr().err
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1
        assert out[0].endswith(".worktrees/YOK-99207")

    def test_epic_without_worker_lanes_is_rejected(self, git_repo, yoke_db):
        # Task-graph workflows require their universal worker lanes first.
        conn = connect_test_db(yoke_db)
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, project_id, project_sequence) "
            "VALUES (99208, 'empty epic', 'implementing', 1, 99208)",
        )
        pin_test_item_workflow(conn, 99208, "epic")
        conn.commit()
        conn.close()

        result = create_worktree(
            99208,
            repo_root=str(git_repo),
            config_path=_config_path(git_repo),
            db_path=yoke_db,
        )

        assert result.error == "no worktrees resolved for item"
        assert result.created is False
