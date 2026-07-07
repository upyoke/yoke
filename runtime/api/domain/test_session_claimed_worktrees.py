"""Tests for :func:`session_claimed_worktrees.claimed_worktrees`.

Covers the four shape rules from the spec body:

* Empty-claim session returns ``[]``.
* Single ``target_kind='item'`` claim returns the machine-local
  checkout worktree path.
* Multi-claim epic (``target_kind='epic_task'``) enumerates per-task
  worktrees, one row per task.
* Released claims (``released_at IS NOT NULL``) are excluded.

The fixture uses a disposable Postgres database and seeds only the
columns the resolver reads — no need to materialise the full Yoke schema.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.session_claimed_worktrees import (
    ClaimedWorktree,
    claimed_worktrees,
)
from yoke_core.engines._doctor_native_sql_test_helpers import (
    connect_disposable_test_db,
)


_TEST_REPO_ROOT_ENV = "YOKE_TEST_SESSION_CLAIMED_REPO_ROOT"


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path / "repo" / "yoke"
    repo_root.mkdir(parents=True)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"projects": {str(repo_root): {"project_id": 1}}}),
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
            worktree TEXT,
            project_id INTEGER
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL,
            task_num INTEGER NOT NULL,
            worktree TEXT,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
            process_key TEXT,
            released_at TEXT
        );
        INSERT INTO projects (id, slug) VALUES (1, 'yoke');
        """,
    )
    c.commit()
    yield c
    c.close()


def _project_id(project="yoke") -> int:
    return {"yoke": 1, "buzz": 2}.get(project, 100)


def _worktree_path(branch: str) -> str:
    return str(Path(os.environ[_TEST_REPO_ROOT_ENV]) / ".worktrees" / branch)


def _seed_item(conn, *, item_id, worktree=None, project="yoke"):
    conn.execute(
        "INSERT INTO items (id, worktree, project_id) VALUES (%s, %s, %s)",
        (item_id, worktree, _project_id(project)),
    )
    conn.commit()


def _seed_epic_task(conn, *, epic_id, task_num, worktree):
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, worktree) "
        "VALUES (%s, %s, %s)",
        (epic_id, task_num, worktree),
    )
    conn.commit()


def _seed_claim(
    conn, *, session_id, target_kind, item_id=None,
    epic_id=None, task_num=None, released_at=None,
):
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, "
        "epic_id, task_num, released_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (session_id, target_kind, item_id, epic_id, task_num, released_at),
    )
    conn.commit()


class TestEmptySession:
    def test_no_claims_returns_empty(self, conn):
        assert claimed_worktrees(conn, session_id="sid-empty") == []

    def test_blank_session_id_returns_empty(self, conn):
        assert claimed_worktrees(conn, session_id="") == []


class TestSingleItemClaim:
    def test_item_claim_returns_computed_worktree_path(self, conn):
        _seed_item(conn, item_id=1691, worktree="YOK-1691")
        _seed_claim(
            conn, session_id="sid-1", target_kind="item", item_id=1691,
        )
        result = claimed_worktrees(conn, session_id="sid-1")
        assert result == [
            ClaimedWorktree(
                item_id=1691,
                task_num=None,
                worktree_path=_worktree_path("YOK-1691"),
            ),
        ]

    def test_item_without_worktree_branch_is_skipped(self, conn):
        # Evidence-only items (--no-worktree) have items.worktree = NULL.
        _seed_item(conn, item_id=42, worktree=None)
        _seed_claim(
            conn, session_id="sid-1", target_kind="item", item_id=42,
        )
        assert claimed_worktrees(conn, session_id="sid-1") == []


class TestMultiTaskEpicClaim:
    def test_per_task_worktrees_enumerated(self, conn):
        # Conduct fan-out: a parent session holds claims on three task
        # lanes of the same epic. Each lane has its own worktree branch.
        _seed_item(conn, item_id=1684, worktree=None)
        _seed_epic_task(conn, epic_id=1684, task_num=2, worktree="YOK-1684-seed")
        _seed_epic_task(
            conn, epic_id=1684, task_num=4, worktree="YOK-1684-callers-a",
        )
        _seed_epic_task(
            conn, epic_id=1684, task_num=9, worktree="YOK-1684-backfill",
        )
        for tnum in (2, 4, 9):
            _seed_claim(
                conn, session_id="sid-parent",
                target_kind="epic_task",
                epic_id=1684, task_num=tnum,
            )
        result = claimed_worktrees(conn, session_id="sid-parent")
        assert [c.task_num for c in result] == [2, 4, 9]
        assert [c.worktree_path for c in result] == [
            _worktree_path("YOK-1684-seed"),
            _worktree_path("YOK-1684-callers-a"),
            _worktree_path("YOK-1684-backfill"),
        ]
        # Single session, three claimed worktrees — the parallel
        # fan-out shape that motivated the rewrite.


class TestReleasedClaimsExcluded:
    def test_released_claim_is_skipped(self, conn):
        _seed_item(conn, item_id=1691, worktree="YOK-1691")
        _seed_claim(
            conn, session_id="sid-1", target_kind="item", item_id=1691,
            released_at="2026-05-14T12:00:00Z",
        )
        assert claimed_worktrees(conn, session_id="sid-1") == []

    def test_mixed_active_and_released(self, conn):
        _seed_item(conn, item_id=1000, worktree="YOK-1000")
        _seed_item(conn, item_id=1001, worktree="YOK-1001")
        _seed_claim(
            conn, session_id="sid-x", target_kind="item", item_id=1000,
            released_at="2026-05-13T00:00:00Z",
        )
        _seed_claim(
            conn, session_id="sid-x", target_kind="item", item_id=1001,
        )
        result = claimed_worktrees(conn, session_id="sid-x")
        assert [c.item_id for c in result] == [1001]


class TestProcessTargetKind:
    def test_process_claim_has_no_worktree(self, conn):
        # target_kind='process' claims (scheduler runs, doctor lanes)
        # have no worktree concept; they contribute nothing.
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, "
            "process_key) VALUES ('sid-1', 'process', 'doctor-run-1')"
        )
        conn.commit()
        assert claimed_worktrees(conn, session_id="sid-1") == []


class TestEpicItemClaimAuthorityIsItemOnly:
    """After the hotfix rollback, an ``item``-level claim authorises
    only ``items.worktree`` for the epic — sibling-branch task
    worktrees require explicit ``target_kind='epic_task'`` claims.
    """

    def test_item_claim_does_not_inherit_sibling_task_worktrees(self, conn):
        _seed_item(conn, item_id=1872, worktree="YOK-1872")
        _seed_epic_task(
            conn, epic_id=1872, task_num=1, worktree="YOK-1872-substrate",
        )
        _seed_epic_task(
            conn, epic_id=1872, task_num=10, worktree="YOK-1872-propagation",
        )
        _seed_claim(
            conn, session_id="sid-orch", target_kind="item", item_id=1872,
        )
        result = claimed_worktrees(conn, session_id="sid-orch")
        assert [c.worktree_path for c in result] == [
            _worktree_path("YOK-1872"),
        ]

    def test_non_epic_item_claim_unchanged(self, conn):
        # Standard non-epic item: single worktree binding.
        _seed_item(conn, item_id=42, worktree="YOK-42")
        _seed_claim(
            conn, session_id="sid-1", target_kind="item", item_id=42,
        )
        assert claimed_worktrees(conn, session_id="sid-1") == [
            ClaimedWorktree(
                item_id=42,
                task_num=None,
                worktree_path=_worktree_path("YOK-42"),
            ),
        ]
