"""Unit tests for the ``workflow_item.epic_task.*`` handlers.

Each test constructs a synthetic :class:`FunctionCallRequest`, patches
:func:`yoke_core.domain.handlers.workflow_item_epic_task._open_connection`
to return a disposable Postgres test-database connection, and asserts
the returned :class:`HandlerOutcome` shape.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.api.domain.workflow_item_update_test_support import (
    add_epic_task as _add_task,
    retained_connection as _conn_cm,
    seed_workflow_item_connection as _seed_conn,
    workflow_item_request as _build_request,
)
from yoke_core.domain.handlers import workflow_item_epic_task as task_handler
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


# ---------------------------------------------------------------------------
# epic_task handlers
# ---------------------------------------------------------------------------


class TestBodyReplaceHandler(unittest.TestCase):
    def test_writes_body_and_returns_line_counts(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first", body="line1\nline2")
        request = _build_request(
            "workflow_item.epic_task.body_replace",
            payload={"body": "one\ntwo\nthree"},
        )
        # Patch epic_task_crud.task_update_body to skip the sync_task_body branch.
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            with patch.object(
                task_handler.epic_task_crud,
                "task_update_body",
                side_effect=lambda c, e, t, b, **kw: (
                    c.execute(
                        "UPDATE epic_tasks SET body=%s "
                        "WHERE epic_id=%s AND task_num=%s",
                        (b, str(e), t),
                    )
                    or "ok"
                ),
            ):
                outcome = task_handler.handle_body_replace(request)
        assert outcome.primary_success is True
        assert outcome.error is None
        assert outcome.result_payload["old_line_count"] == 2
        assert outcome.result_payload["new_line_count"] == 3

    def test_not_found(self):
        conn = _seed_conn()
        request = _build_request(
            "workflow_item.epic_task.body_replace",
            payload={"body": "x"},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_body_replace(request)
        assert outcome.primary_success is False
        assert outcome.error.code == "target_not_found"


class TestSplitHandler(unittest.TestCase):
    def test_splits_parent_into_children(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "parent")
        request = _build_request(
            "workflow_item.epic_task.split",
            payload={
                "children": [
                    {"title": "child-A"},
                    {"title": "child-B"},
                ]
            },
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_split(request)
        assert outcome.primary_success is True
        assert outcome.result_payload["new_task_nums"] == [2, 3]

    def test_target_not_found(self):
        conn = _seed_conn()
        request = _build_request(
            "workflow_item.epic_task.split",
            task_num=99,
            payload={"children": [{"title": "child"}]},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_split(request)
        assert outcome.error.code == "target_not_found"


class TestReassignHandler(unittest.TestCase):
    def test_updates_worktree(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first", worktree="old-wt")
        request = _build_request(
            "workflow_item.epic_task.reassign",
            payload={"new_worktree": "new-wt"},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_reassign(request)
        assert outcome.primary_success is True
        assert outcome.result_payload["old_worktree"] == "old-wt"
        assert outcome.result_payload["new_worktree"] == "new-wt"

    def test_not_found(self):
        conn = _seed_conn()
        request = _build_request(
            "workflow_item.epic_task.reassign",
            task_num=99,
            payload={"new_worktree": "new-wt"},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_reassign(request)
        assert outcome.error.code == "target_not_found"


class TestAddHandler(unittest.TestCase):
    def test_appends_task(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first")
        # add omits task_num — payload provides the rest.
        request = FunctionCallRequest(
            function="workflow_item.epic_task.add",
            actor=ActorContext(actor_id="test", session_id="s-1"),
            target=TargetRef(kind="epic_task", epic_id=100),
            payload={"title": "added", "body": "body"},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_add(request)
        assert outcome.primary_success is True
        assert outcome.result_payload["task_num"] == 2
        assert outcome.result_payload["title"] == "added"

    def test_rejects_empty_title(self):
        conn = _seed_conn()
        request = FunctionCallRequest(
            function="workflow_item.epic_task.add",
            actor=ActorContext(actor_id="test", session_id="s-1"),
            target=TargetRef(kind="epic_task", epic_id=100),
            payload={"title": ""},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_add(request)
        assert outcome.error.code == "invalid_payload"


class TestRemoveHandler(unittest.TestCase):
    def test_removes_and_cascades(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first")
        _add_task(conn, 100, 2, "depends_on_1", dependencies="1")
        request = _build_request(
            "workflow_item.epic_task.remove",
            payload={"reason": "no longer needed"},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_remove(request)
        assert outcome.primary_success is True
        cascade = outcome.result_payload["cascade_updated"]
        # Allow either int or string keys (pydantic dump path varies).
        normalized = {int(k): v for k, v in cascade.items()}
        assert normalized == {2: ""}

    def test_not_found(self):
        conn = _seed_conn()
        request = _build_request(
            "workflow_item.epic_task.remove",
            task_num=99,
            payload={"reason": ""},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_remove(request)
        assert outcome.error.code == "target_not_found"


class TestMetadataUpdateHandler(unittest.TestCase):
    def test_updates_fields(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first")
        request = _build_request(
            "workflow_item.epic_task.metadata_update",
            payload={"fields": {"title": "renamed", "github_issue": "#42"}},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_metadata_update(request)
        assert outcome.primary_success is True
        assert outcome.result_payload["updated_fields"]["title"] == "renamed"

    def test_unknown_field_rejected(self):
        conn = _seed_conn()
        _add_task(conn, 100, 1, "first")
        request = _build_request(
            "workflow_item.epic_task.metadata_update",
            payload={"fields": {"status": "planned"}},
        )
        with patch.object(task_handler, "_open_connection", lambda: _conn_cm(conn)):
            outcome = task_handler.handle_metadata_update(request)
        assert outcome.error.code == "invalid_payload"


if __name__ == "__main__":
    unittest.main()
