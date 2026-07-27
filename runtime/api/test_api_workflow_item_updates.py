"""Integration tests for ``workflow_item.*`` function-call FastAPI routes.

Each test posts a synthetic envelope through the live ``/v1/functions/call``
endpoint and asserts the response shape. Claim verification is bypassed
by patching the dispatcher's claim helper so the tests can focus on
handler wiring and the dispatcher round-trip.
"""

from __future__ import annotations

from runtime.api.workflow_item_update_api_test_support import (
    WorkflowItemUpdateAPIBase as _BaseAPI,
    add_task as _add_task,
    envelope as _envelope,
)
from yoke_core.domain.yoke_function_registry import (
    list_entries,
)


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
            json=_envelope(
                "workflow_item.epic_task.body_replace",
                payload={"body": "new\nlonger\nbody"},
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["result"]["old_line_count"] == 2
        assert body["result"]["new_line_count"] == 3

    def test_target_not_found_returns_handler_error(self):
        response = self.client.post(
            "/v1/functions/call",
            json=_envelope(
                "workflow_item.epic_task.body_replace",
                task_num=99,
                payload={"body": "x"},
            ),
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
                payload={
                    "children": [
                        {"title": "child-A"},
                        {"title": "child-B"},
                    ]
                },
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
            json=_envelope(
                "workflow_item.epic_task.reassign", payload={"new_worktree": "new"}
            ),
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
            json=_envelope(
                "workflow_item.epic_task.remove", payload={"reason": "no longer needed"}
            ),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
