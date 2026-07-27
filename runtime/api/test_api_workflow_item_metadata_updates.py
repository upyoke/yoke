"""Metadata and progress-note workflow-item API tests."""

from runtime.api.workflow_item_update_api_test_support import (
    WorkflowItemUpdateAPIBase as _BaseAPI,
    add_task as _add_task,
    envelope as _envelope,
)


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
