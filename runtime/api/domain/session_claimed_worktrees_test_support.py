# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

import json

import os

from pathlib import Path

import pytest

from yoke_core.domain.schema_init_apply import execute_schema_script

from yoke_core.domain.session_claimed_worktrees import (
    ClaimedWorktree,
    claimed_worktrees,
)

from yoke_core.domain.work_claim_targets import (
    WorkClaimTarget,
    make_epic_task_target,
    make_item_target,
)

from runtime.api.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)

_TEST_REPO_ROOT_ENV = "YOKE_TEST_SESSION_CLAIMED_REPO_ROOT"


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path / "repo" / "yoke"
    repo_root.mkdir(parents=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "active_env": "local",
                "connection_projects": {
                    "local": [{"checkout": str(repo_root), "project_id": 1}]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    monkeypatch.setenv(_TEST_REPO_ROOT_ENV, str(repo_root))
    c = connect_disposable_test_db()
    execute_schema_script(
        c,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            path TEXT,
            lane_role TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            item_worktree_id INTEGER,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            released_at TIMESTAMPTZ
        );
        INSERT INTO projects (id, slug) VALUES (1, 'yoke');
        """,
    )
    c.commit()
    yield c
    c.close()


def _project_id(project="yoke") -> int:
    return {"yoke": 1, "externalwebapp": 2}.get(project, 100)


def _worktree_path(branch: str) -> str:
    return str(Path(os.environ[_TEST_REPO_ROOT_ENV]) / ".worktrees" / branch)


def _seed_item(conn, *, item_id, worktree=None, project="yoke"):
    conn.execute(
        "INSERT INTO items (id, project_id) VALUES (%s, %s)",
        (item_id, _project_id(project)),
    )
    if worktree:
        conn.execute(
            "INSERT INTO item_worktrees "
            "(item_id, branch, path, lane_role, state, created_at, "
            "updated_at) "
            "VALUES (%s, %s, %s, 'implementation', 'active', %s, %s)",
            (
                item_id,
                worktree,
                _worktree_path(worktree),
                parse_instant("2026-05-14T12:00:00Z"),
                parse_instant("2026-05-14T12:00:00Z"),
            ),
        )
    conn.commit()


def _seed_epic_task(conn, *, epic_id, task_num, worktree):
    row = conn.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, path, lane_role, state, created_at, updated_at) "
        "VALUES (%s, %s, %s, 'worker', 'active', %s, %s) RETURNING id",
        (
            epic_id,
            worktree,
            _worktree_path(worktree),
            parse_instant("2026-05-14T12:00:00Z"),
            parse_instant("2026-05-14T12:00:00Z"),
        ),
    ).fetchone()
    lane_id = int(row["id"] if hasattr(row, "keys") else row[0])
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, item_worktree_id) VALUES (%s, %s, %s)",
        (epic_id, task_num, lane_id),
    )
    conn.commit()


def _seed_claim(
    conn,
    *,
    session_id,
    target_kind,
    item_id=None,
    epic_id=None,
    task_num=None,
    released_at=None,
):
    target = (
        make_item_target(item_id)
        if target_kind == "item"
        else make_epic_task_target(epic_id, task_num)
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, released_at) VALUES (%s, %s, %s, %s)",
        (
            session_id,
            target_kind,
            target.scope_json(),
            parse_instant(released_at) if released_at is not None else None,
        ),
    )
    conn.commit()
