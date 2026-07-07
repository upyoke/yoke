"""Integration tests for ``workflow_item.*`` function-call FastAPI routes.

Each test posts a synthetic envelope through the live ``/v1/functions/call``
endpoint and asserts the response shape. Claim verification is bypassed
by patching the dispatcher's claim helper so the tests can focus on
handler wiring and the dispatcher round-trip.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
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
    list_entries, reset_registry_for_tests,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.api.main import app


_TASKS_SCHEMA = """
CREATE TABLE epic_tasks (
    id INTEGER PRIMARY KEY, epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
    title TEXT, worktree TEXT, context_estimate TEXT, dependencies TEXT,
    status TEXT DEFAULT 'planning',
    dispatch_attempts INTEGER DEFAULT 0, body TEXT, github_issue TEXT,
    branch TEXT, worktree_path TEXT, blocked_by TEXT,
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
        apply_fixture_ddl(conn, _TASKS_SCHEMA)
    finally:
        conn.close()


def _add_task(conn, epic_id, task_num, title, **kwargs):
    p = _p(conn)
    conn.execute(
        "INSERT INTO epic_tasks (epic_id, task_num, title, worktree, "
        "context_estimate, dependencies, status, body) VALUES "
        f"({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
        (
            str(epic_id), task_num, title,
            kwargs.get("worktree", ""), kwargs.get("context_estimate", ""),
            kwargs.get("dependencies", ""), kwargs.get("status", "planning"),
            kwargs.get("body", ""),
        ),
    )
    conn.commit()


@contextmanager
def _conn_cm(conn):
    yield conn


def _task_update_body_stub(conn, epic_id, task_num, body, **_kwargs):
    p = _p(conn)
    conn.execute(
        f"UPDATE epic_tasks SET body={p} WHERE epic_id={p} AND task_num={p}",
        (body, str(epic_id), task_num),
    )
    return "ok"


def _progress_note_insert_stub(
    conn, epic_id, task_num, note_num, body, commit_hash="",
):
    p = _p(conn)
    conn.execute(
        "INSERT INTO epic_progress_notes "
        "(epic_id, task_num, note_num, body, commit_hash, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, '2026-01-01T00:00:00Z')",
        (str(epic_id), task_num, note_num, body, commit_hash),
    )
    return "ok"


def _envelope(function: str, *, epic_id=100, task_num=1, payload=None):
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


class _BaseAPI(unittest.TestCase):
    """Shared setup: register handlers + stub claim verification."""

    @classmethod
    def setUpClass(cls):
        # Mute event emission so the events module never hits a live DB.
        cls._event_patches = [
            patch.object(yoke_function_dispatch_events, "emit_called",
                         lambda *a, **kw: None),
            patch.object(yoke_function_dispatch_events,
                         "emit_idempotency_replay", lambda *a, **kw: None),
            patch.object(yoke_function_dispatch_events,
                         "emit_downstream_degraded", lambda *a, **kw: None),
            patch.object(yoke_function_dispatch_events, "serialize_payload",
                         lambda _p: (0, "")),
            patch.object(yoke_function_dispatch_claims, "who_claims_for_item",
                         lambda _i: {"session_id": "s-1"}),
            patch("yoke_core.domain.yoke_function_dispatch._idempotency_lookup",
                  lambda _f, _r: None),
        ]
        for p in cls._event_patches:
            p.start()
        reset_registry_for_tests()
        register_all_handlers()

    @classmethod
    def tearDownClass(cls):
        for p in cls._event_patches:
            p.stop()
        reset_registry_for_tests()

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self._db_ctx = init_test_db(
            Path(self._tmpdir.name), apply_schema=_apply_tasks_schema,
        )
        self._db_path = self._db_ctx.__enter__()
        self.conn = connect_test_db(self._db_path)
        self.client = TestClient(app)
        auth = mint_api_auth_context(self.conn)
        self.client.headers.update(auth.headers)
        self._conn_patches = [
            patch.object(task_handler, "_open_connection",
                         lambda: _conn_cm(self.conn)),
            patch.object(progress_handler, "_open_connection",
                         lambda: _conn_cm(self.conn)),
            # Stub the task_update_body call to skip sync.
            patch.object(
                task_handler.epic_task_crud, "task_update_body",
                side_effect=_task_update_body_stub,
            ),
            patch.object(
                progress_handler.epic, "progress_note_insert",
                side_effect=_progress_note_insert_stub,
            ),
        ]
        for p in self._conn_patches:
            p.start()

    def tearDown(self):
        for p in self._conn_patches:
            p.stop()
        self.conn.close()
        self._db_ctx.__exit__(None, None, None)
        self._tmpdir.cleanup()


class TestRegistrationCoverage(_BaseAPI):
    """Smoke test that all seven function ids are registered."""

    def test_all_seven_ids_present(self):
        ids = {e.function_id for e in list_entries()}
        for fid in (
            "workflow_item.epic_task.body_replace",
            "workflow_item.epic_task.split",
            "workflow_item.epic_task.reassign",
            "workflow_item.epic_task.add",
            "workflow_item.epic_task.remove",
            "workflow_item.epic_task.metadata_update",
            "workflow_item.epic_progress_note.append",
        ):
            assert fid in ids, f"function id {fid!r} not registered"

    def test_schema_endpoint_returns_request_shape(self):
        response = self.client.get(
            "/v1/functions/schema/workflow_item.epic_task.body_replace"
        )
        assert response.status_code == 200
        schema = response.json()
        assert "properties" in schema
        assert "body" in schema["properties"]


class TestBodyReplaceAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "first", body="old\nbody")
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope("workflow_item.epic_task.body_replace",
                           payload={"body": "new\nlonger\nbody"}),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["result"]["old_line_count"] == 2
        assert body["result"]["new_line_count"] == 3

    def test_target_not_found_returns_handler_error(self):
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope("workflow_item.epic_task.body_replace",
                           task_num=99, payload={"body": "x"}),
        )
        # Handler returns success=False with target_not_found; HTTP 400 (default).
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "target_not_found"


class TestAddAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "first")
        envelope = _envelope(
            "workflow_item.epic_task.add",
            payload={"title": "added", "body": "body"},
        )
        envelope["target"].pop("task_num", None)
        response = self.client.post("/v1/functions/call", json=envelope)
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["result"]["task_num"] == 2


class TestSplitAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "parent")
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope(
                "workflow_item.epic_task.split",
                payload={"children": [
                    {"title": "child-A"}, {"title": "child-B"},
                ]},
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["new_task_nums"] == [2, 3]


class TestReassignAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "first", worktree="old")
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope("workflow_item.epic_task.reassign",
                           payload={"new_worktree": "new"}),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["new_worktree"] == "new"
        assert body["result"]["old_worktree"] == "old"


class TestRemoveAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "first")
        _add_task(self.conn, 100, 2, "second", dependencies="1")
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope("workflow_item.epic_task.remove",
                           payload={"reason": "no longer needed"}),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True


class TestMetadataUpdateAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "first")
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope(
                "workflow_item.epic_task.metadata_update",
                payload={"fields": {"title": "renamed"}},
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["updated_fields"]["title"] == "renamed"


class TestProgressNoteAppendAPI(_BaseAPI):
    def test_round_trip(self):
        _add_task(self.conn, 100, 1, "first")
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope(
                "workflow_item.epic_progress_note.append",
                payload={"note_num": 1, "body": "first note"},
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["note_num"] == 1


if __name__ == "__main__":
    unittest.main()
