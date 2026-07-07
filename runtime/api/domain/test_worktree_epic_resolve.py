"""Epic multi-worktree coverage for ``resolve_item_worktree``."""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

from yoke_core.domain import db_backend
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.worktree import resolve_item_worktree
from yoke_core.domain.worktree_test_helpers import (  # noqa: F401
    git_repo,
    yoke_db,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _add_item_and_project(conn, epic_id: int, git_repo) -> None:
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, worktree, project_id, project_sequence) "
        f"VALUES ({p}, 'Epic', 'epic', 'reviewed-implementation', {p}, {p}, {p})",
        (epic_id, f"YOK-{epic_id}", SEED_PROJECT_IDS["yoke"], epic_id),
    )
    register_machine_checkout(
        git_repo.parent / "machine-config",
        git_repo,
        SEED_PROJECT_IDS["yoke"],
    )


def _add_git_worktree(git_repo, branch: str):
    path = git_repo / ".worktrees" / branch
    subprocess.run(
        ["git", "worktree", "add", str(path), "-b", branch, "main"],
        cwd=str(git_repo), check=True, capture_output=True,
    )
    return path


class TestResolveEpicWorktree:
    def test_dispatch_chains_resolve_as_task_worktrees(self, git_repo, yoke_db):
        epic_id = 88
        branch_a = f"YOK-{epic_id}-alpha"
        branch_b = f"YOK-{epic_id}-beta"
        path_a = _add_git_worktree(git_repo, branch_a)
        path_b = _add_git_worktree(git_repo, branch_b)

        conn = connect_test_db(yoke_db)
        execute_schema_script(conn, """
            CREATE TABLE epic_dispatch_chains (
                id INTEGER PRIMARY KEY,
                epic_id TEXT,
                worktree TEXT,
                worktree_path TEXT,
                queue TEXT,
                current_index INTEGER,
                current_task TEXT
            );
        """)
        _add_item_and_project(conn, epic_id, git_repo)
        p = _placeholder(conn)
        for task, branch, path in (("001", branch_a, path_a), ("002", branch_b, path_b)):
            conn.execute(
                "INSERT INTO epic_dispatch_chains "
                "(epic_id, worktree, worktree_path, queue, current_index, current_task) "
                f"VALUES ({p}, {p}, {p}, {p}, 0, {p})",
                (str(epic_id), branch, str(path), f'["{task}"]', task),
            )
        conn.commit()
        conn.close()

        result = resolve_item_worktree(f"YOK-{epic_id}", db_path=yoke_db)

        assert result.scope == "epic-tasks"
        assert result.exists is True
        assert result.has_multiple is True
        assert result.paths == (str(path_a), str(path_b))
        assert result.branches == (branch_a, branch_b)
        assert result.path == ""
        assert result.branch == ""

    def test_task_rows_dedupe_shared_worktree_lanes(self, git_repo, yoke_db):
        epic_id = 89
        branch = f"YOK-{epic_id}-shared"
        path = _add_git_worktree(git_repo, branch)

        conn = connect_test_db(yoke_db)
        execute_schema_script(conn, """
            CREATE TABLE epic_tasks (
                id INTEGER PRIMARY KEY,
                epic_id TEXT,
                task_num INTEGER,
                title TEXT,
                status TEXT,
                worktree TEXT,
                branch TEXT,
                worktree_path TEXT
            );
        """)
        _add_item_and_project(conn, epic_id, git_repo)
        p = _placeholder(conn)
        for task_num in (1, 2):
            conn.execute(
                "INSERT INTO epic_tasks "
                "(epic_id, task_num, title, status, worktree, branch, worktree_path) "
                f"VALUES ({p}, {p}, {p}, 'reviewed-implementation', {p}, {p}, {p})",
                (str(epic_id), task_num, f"Task {task_num}", branch, branch, str(path)),
            )
        conn.commit()
        conn.close()

        result = resolve_item_worktree(f"YOK-{epic_id}", db_path=yoke_db)

        assert result.scope == "epic-tasks"
        assert result.exists is True
        assert result.has_multiple is False
        assert result.path == str(path)
        assert result.branch == branch
        assert result.paths == (str(path),)

    def test_cli_rejects_singular_path_for_multiple_epic_lanes(
        self, git_repo, yoke_db, capsys,
    ):
        epic_id = 90
        branch_a = f"YOK-{epic_id}-one"
        branch_b = f"YOK-{epic_id}-two"
        path_a = _add_git_worktree(git_repo, branch_a)
        path_b = _add_git_worktree(git_repo, branch_b)

        conn = connect_test_db(yoke_db)
        conn.execute(
            "CREATE TABLE epic_dispatch_chains "
            "(epic_id TEXT, worktree TEXT, worktree_path TEXT)"
        )
        _add_item_and_project(conn, epic_id, git_repo)
        p = _placeholder(conn)
        conn.execute(
            f"INSERT INTO epic_dispatch_chains VALUES ({p}, {p}, {p})",
            (str(epic_id), branch_a, str(path_a)),
        )
        conn.execute(
            f"INSERT INTO epic_dispatch_chains VALUES ({p}, {p}, {p})",
            (str(epic_id), branch_b, str(path_b)),
        )
        conn.commit()
        conn.close()

        from yoke_core.domain import worktree as worktree_cli

        with patch.dict(os.environ, {"YOKE_DB": yoke_db}):
            with patch.object(
                sys, "argv",
                ["worktree", "resolve", f"YOK-{epic_id}", "--field", "path"],
            ):
                exit_code = worktree_cli.main()
            with patch.object(
                sys, "argv",
                ["worktree", "resolve", f"YOK-{epic_id}", "--field", "paths"],
            ):
                paths_exit = worktree_cli.main()

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "resolves to 2 task worktrees" in captured.err
        assert paths_exit == 0
        assert str(path_a) in captured.out
        assert str(path_b) in captured.out
