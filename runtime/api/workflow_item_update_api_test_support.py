"""FastAPI test harness for workflow-item update functions."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.api.main import app
from yoke_core.domain import (
    db_backend,
    yoke_function_dispatch_claims,
    yoke_function_dispatch_events,
)
from yoke_core.domain.handlers import (
    workflow_item_epic_progress_note as progress_handler,
    workflow_item_epic_task as task_handler,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import (
    reset_registry_for_tests,
)

TASKS_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY, workflow_id TEXT, workflow_version_id INTEGER,
    project_id INTEGER DEFAULT 1
);
CREATE TABLE item_worktrees (
    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, branch TEXT NOT NULL,
    path TEXT, lane_role TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, released_at TEXT
);
CREATE TABLE epic_tasks (
    id INTEGER PRIMARY KEY, epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
    title TEXT, item_worktree_id INTEGER, context_estimate TEXT, dependencies TEXT,
    status TEXT DEFAULT 'planning',
    dispatch_attempts INTEGER DEFAULT 0, body TEXT, github_issue TEXT,
    branch TEXT, worktree_path TEXT,
    max_attempts INTEGER DEFAULT 5, agent_id TEXT, last_heartbeat TEXT,
    UNIQUE(epic_id, task_num)
);
CREATE TABLE epic_progress_notes (
    id INTEGER PRIMARY KEY, epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
    note_num INTEGER NOT NULL, body TEXT, commit_hash TEXT,
    synced_to_github INTEGER DEFAULT 0, created_at TEXT NOT NULL,
    UNIQUE(epic_id, task_num, note_num)
);
"""


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_tasks_schema() -> None:
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, TASKS_SCHEMA)
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
    finally:
        conn.close()


def add_task(conn, epic_id, task_num, title, **kwargs):
    from yoke_core.domain.item_worktrees import record_worker_item_worktree
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    p = _p(conn)
    if (
        conn.execute(f"SELECT 1 FROM items WHERE id = {p}", (int(epic_id),)).fetchone()
        is None
    ):
        workflow_id, version_id = resolve_current_workflow_pin(conn, "epic")
        conn.execute(
            "INSERT INTO items "
            "(id, workflow_id, workflow_version_id, project_id) "
            f"VALUES ({p}, {p}, {p}, 1)",
            (int(epic_id), workflow_id, version_id),
        )
    worktree = kwargs.get("worktree", "")
    lane_id = None
    if worktree:
        lane_id = int(
            record_worker_item_worktree(
                conn,
                item_id=int(epic_id),
                branch=worktree,
                path=None,
            )["id"]
        )
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, title, item_worktree_id, "
        "context_estimate, dependencies, status, body) VALUES "
        f"({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
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


@contextmanager
def retained_connection(conn):
    yield conn


def task_update_body_stub(conn, epic_id, task_num, body, **_kwargs):
    p = _p(conn)
    conn.execute(
        f"UPDATE epic_tasks SET body={p} WHERE epic_id={p} AND task_num={p}",
        (body, str(epic_id), task_num),
    )
    return "ok"


def progress_note_insert_stub(
    conn,
    epic_id,
    task_num,
    note_num,
    body,
    commit_hash="",
):
    p = _p(conn)
    conn.execute(
        "INSERT INTO epic_progress_notes "
        "(epic_id, task_num, note_num, body, commit_hash, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, '2026-01-01T00:00:00Z')",
        (str(epic_id), task_num, note_num, body, commit_hash),
    )
    return "ok"


def envelope(function: str, *, epic_id=100, task_num=1, payload=None):
    return {
        "function": function,
        "version": "v1",
        "actor": {"actor_id": "test", "session_id": "s-1"},
        "target": {
            "kind": "epic_task",
            "epic_id": epic_id,
            "task_num": task_num,
            "project_id": "yoke",
        },
        "payload": payload or {},
    }


class WorkflowItemUpdateAPIBase(unittest.TestCase):
    """Register handlers and isolate connections for workflow-item API tests."""

    @classmethod
    def setUpClass(cls):
        cls._event_patches = [
            patch.object(
                yoke_function_dispatch_events, "emit_called", lambda *a, **kw: None
            ),
            patch.object(
                yoke_function_dispatch_events,
                "emit_idempotency_replay",
                lambda *a, **kw: None,
            ),
            patch.object(
                yoke_function_dispatch_events,
                "emit_downstream_degraded",
                lambda *a, **kw: None,
            ),
            patch.object(
                yoke_function_dispatch_events, "serialize_payload", lambda _p: (0, "")
            ),
            patch.object(
                yoke_function_dispatch_claims,
                "who_claims_for_item",
                lambda _i: {"session_id": "s-1"},
            ),
            patch(
                "yoke_core.domain.yoke_function_dispatch._idempotency_lookup",
                lambda _f, _r: None,
            ),
        ]
        for event_patch in cls._event_patches:
            event_patch.start()
        reset_registry_for_tests()
        register_all_handlers()

    @classmethod
    def tearDownClass(cls):
        for event_patch in cls._event_patches:
            event_patch.stop()
        reset_registry_for_tests()

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmpdir.name),
            apply_schema=_apply_tasks_schema,
        )
        self._db_path = self._db_ctx.__enter__()
        self.conn = connect_test_db(self._db_path)
        self.client = TestClient(app)
        auth = mint_api_auth_context(self.conn)
        self.client.headers.update(auth.headers)
        self._conn_patches = [
            patch.object(
                task_handler,
                "_open_connection",
                lambda: retained_connection(self.conn),
            ),
            patch.object(
                progress_handler,
                "_open_connection",
                lambda: retained_connection(self.conn),
            ),
            patch.object(
                task_handler.epic_task_crud,
                "task_update_body",
                side_effect=task_update_body_stub,
            ),
            patch.object(
                progress_handler.epic,
                "progress_note_insert",
                side_effect=progress_note_insert_stub,
            ),
        ]
        for connection_patch in self._conn_patches:
            connection_patch.start()

    def tearDown(self):
        for connection_patch in self._conn_patches:
            connection_patch.stop()
        self.conn.close()
        self._db_ctx.__exit__(None, None, None)
        self._tmpdir.cleanup()
