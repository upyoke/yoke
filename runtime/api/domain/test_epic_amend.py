"""Unit tests for ``yoke_core.domain.epic_amend``.

Each test runs against a disposable Postgres database seeded with the
``epic_tasks`` schema. Single-transaction behavior is verified by the
sibling-dependency cascade tests on ``task_remove`` and ``task_split``.
"""

from __future__ import annotations

import unittest
from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from yoke_core.domain import epic_amend
from runtime.api.task_files_touched_test_support import declare_task_files
from yoke_core.domain.epic_task_membership import membership_is_finalized
from yoke_core.domain.epic_task_scope import finalize_generated_task_scopes
from yoke_core.domain.task_files_touched import parse_files_touched


class _DatabaseCase(unittest.TestCase):
    def _seed_conn(self) -> Any:
        return self.enterContext(pg_testdb.test_database())


def _add_row(conn, epic_id, task_num, title, **kwargs):
    item = conn.execute(
        "SELECT id FROM items WHERE id=%s",
        (int(epic_id),),
    ).fetchone()
    if item is None:
        insert_item(
            conn,
            id=int(epic_id),
            workflow_id="epic",
            status="planned",
        )
    lane_id = None
    branch = kwargs.get("worktree", "")
    if branch:
        lane_id = insert_item_worktree(
            conn,
            item_id=int(epic_id),
            branch=branch,
            lane_role="worker",
        )["id"]
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, title, item_worktree_id, "
        "context_estimate, dependencies, status, body) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            str(epic_id),
            task_num,
            title,
            lane_id,
            kwargs.get("context_estimate", ""),
            kwargs.get("dependencies", ""),
            kwargs.get("status", "planning"),
            kwargs.get("body", ""),
        ),
    )
    conn.commit()


def _finalize_rows(conn, epic_id: int, *task_nums: int) -> None:
    for task_num in task_nums:
        declare_task_files(conn, epic_id, task_num, [])
    conn.commit()
    finalize_generated_task_scopes(conn, epic_id)
    assert membership_is_finalized(conn, epic_id)


def _task_states(conn, epic_id: int) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT task_num, body FROM epic_tasks WHERE epic_id=%s ORDER BY task_num",
        (int(epic_id),),
    ).fetchall()
    return [(r["task_num"], parse_files_touched(r["body"]).state) for r in rows]


class TestTaskAdd(_DatabaseCase):
    def test_appends_at_next_task_num(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        result = epic_amend.task_add(
            conn,
            100,
            title="second",
            body="body-text",
        )
        assert result.task_num == 2
        row = conn.execute(
            "SELECT title, body FROM epic_tasks WHERE epic_id='100' AND task_num=2"
        ).fetchone()
        assert row["title"] == "second"
        assert row["body"] == "body-text"

    def test_first_task_starts_at_one(self):
        conn = self._seed_conn()
        result = epic_amend.task_add(conn, 200, title="first")
        assert result.task_num == 1

    def test_rejects_empty_title(self):
        conn = self._seed_conn()
        with pytest.raises(ValueError, match="title"):
            epic_amend.task_add(conn, 100, title="")

    def test_reopens_finalized_membership_before_add(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        _finalize_rows(conn, 100, 1)

        result = epic_amend.task_add(conn, 100, title="second")

        assert result.task_num == 2
        assert _task_states(conn, 100) == [(1, "no_files"), (2, "missing")]
        assert not membership_is_finalized(conn, 100)


class TestTaskReassign(_DatabaseCase):
    def test_updates_task_lane_reference(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first", worktree="old-wt")
        result = epic_amend.task_reassign(conn, 100, 1, "new-wt")
        assert result.old_worktree == "old-wt"
        assert result.new_worktree == "new-wt"
        row = conn.execute(
            "SELECT iw.branch FROM epic_tasks t JOIN item_worktrees iw "
            "ON iw.id=t.item_worktree_id "
            "WHERE t.epic_id='100' AND t.task_num=1"
        ).fetchone()
        assert row["branch"] == "new-wt"

    def test_rejects_empty_worktree(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        with pytest.raises(ValueError, match="new_worktree"):
            epic_amend.task_reassign(conn, 100, 1, "")

    def test_raises_when_task_missing(self):
        conn = self._seed_conn()
        with pytest.raises(LookupError):
            epic_amend.task_reassign(conn, 100, 99, "any")


class TestTaskRemove(_DatabaseCase):
    def test_removes_row(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        _add_row(conn, 100, 2, "second")
        epic_amend.task_remove(conn, 100, 1)
        rows = conn.execute(
            "SELECT task_num FROM epic_tasks WHERE epic_id='100'"
        ).fetchall()
        assert [r["task_num"] for r in rows] == [2]

    def test_cascade_removes_dependency_token(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        _add_row(conn, 100, 2, "second", dependencies="1")
        _add_row(conn, 100, 3, "third", dependencies="1,2")
        result = epic_amend.task_remove(conn, 100, 1)
        assert 2 in result.cascade_updated
        assert 3 in result.cascade_updated
        rows = conn.execute(
            "SELECT task_num, dependencies FROM epic_tasks WHERE epic_id='100' "
            "ORDER BY task_num"
        ).fetchall()
        deps = {r["task_num"]: r["dependencies"] for r in rows}
        assert deps[2] == ""
        assert deps[3] == "2"

    def test_raises_when_task_missing(self):
        conn = self._seed_conn()
        with pytest.raises(LookupError):
            epic_amend.task_remove(conn, 100, 99)

    def test_reopens_finalized_membership_before_remove(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        _add_row(conn, 100, 2, "second")
        _finalize_rows(conn, 100, 1, 2)

        epic_amend.task_remove(conn, 100, 1)

        assert _task_states(conn, 100) == [(2, "no_files")]
        assert not membership_is_finalized(conn, 100)


class TestTaskMetadataUpdate(_DatabaseCase):
    def test_updates_whitelisted_fields(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first", context_estimate="2k")
        result = epic_amend.task_metadata_update(
            conn,
            100,
            1,
            {"title": "renamed", "context_estimate": "4k", "github_issue": "#42"},
        )
        assert result.updated_fields["title"] == "renamed"
        assert result.updated_fields["context_estimate"] == "4k"
        row = conn.execute(
            "SELECT title, context_estimate, github_issue FROM epic_tasks "
            "WHERE epic_id='100' AND task_num=1"
        ).fetchone()
        assert row["title"] == "renamed"
        assert row["context_estimate"] == "4k"
        assert row["github_issue"] == "#42"

    def test_rejects_unknown_field(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        with pytest.raises(ValueError, match="item-worktrees path-record"):
            epic_amend.task_metadata_update(
                conn,
                100,
                1,
                {"status": "planned", "worktree": "lane"},
            )

    def test_rejects_empty_fields(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "first")
        with pytest.raises(ValueError, match="empty"):
            epic_amend.task_metadata_update(conn, 100, 1, {})

    def test_raises_when_task_missing(self):
        conn = self._seed_conn()
        with pytest.raises(LookupError):
            epic_amend.task_metadata_update(conn, 100, 99, {"title": "x"})


class TestTaskSplit(_DatabaseCase):
    def test_creates_children_at_max_plus_one(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "parent")
        _add_row(conn, 100, 2, "sibling")
        result = epic_amend.task_split(
            conn,
            100,
            1,
            [{"title": "child-A", "body": "A-body"}, {"title": "child-B"}],
        )
        assert result.parent_task_num == 1
        assert result.new_task_nums == [3, 4]
        rows = conn.execute(
            "SELECT task_num, title, body FROM epic_tasks "
            "WHERE epic_id='100' ORDER BY task_num"
        ).fetchall()
        title_map = {r["task_num"]: r["title"] for r in rows}
        body_map = {r["task_num"]: r["body"] for r in rows}
        # Parent row removed; siblings + 2 children present.
        assert 1 not in title_map
        assert title_map[2] == "sibling"
        assert title_map[3] == "child-A"
        assert title_map[4] == "child-B"
        assert body_map[3] == "A-body"

    def test_redirects_sibling_dependencies_to_first_child(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "parent")
        _add_row(conn, 100, 2, "sibling", dependencies="1")
        _add_row(conn, 100, 3, "other", dependencies="1,2")
        result = epic_amend.task_split(
            conn,
            100,
            1,
            [{"title": "child-A"}, {"title": "child-B"}],
        )
        assert result.new_task_nums == [4, 5]
        # First child is 4 — sibling deps that referenced 1 now reference 4.
        rows = conn.execute(
            "SELECT task_num, dependencies FROM epic_tasks "
            "WHERE epic_id='100' AND task_num IN (2, 3) ORDER BY task_num"
        ).fetchall()
        deps = {r["task_num"]: r["dependencies"] for r in rows}
        assert deps[2] == "4"
        assert deps[3] == "4,2"

    def test_rejects_empty_children(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "parent")
        with pytest.raises(ValueError, match="children"):
            epic_amend.task_split(conn, 100, 1, [])

    def test_rejects_child_missing_title(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "parent")
        with pytest.raises(ValueError, match="title"):
            epic_amend.task_split(
                conn,
                100,
                1,
                [{"body": "no title"}],
            )

    def test_raises_when_parent_missing(self):
        conn = self._seed_conn()
        with pytest.raises(LookupError):
            epic_amend.task_split(
                conn,
                100,
                99,
                [{"title": "x"}],
            )

    def test_reopens_finalized_membership_before_split(self):
        conn = self._seed_conn()
        _add_row(conn, 100, 1, "parent")
        _add_row(conn, 100, 2, "sibling")
        _finalize_rows(conn, 100, 1, 2)

        result = epic_amend.task_split(
            conn,
            100,
            1,
            [{"title": "child-A"}, {"title": "child-B"}],
        )

        assert result.new_task_nums == [3, 4]
        assert _task_states(conn, 100) == [
            (2, "no_files"),
            (3, "missing"),
            (4, "missing"),
        ]
        assert not membership_is_finalized(conn, 100)


if __name__ == "__main__":
    unittest.main()
