"""Status-event contracts for item HTTP routes.

The compatibility approval route only exposes an Inbox request and never
mutates item status. The general item-write route rejects status patches,
leaving lifecycle transitions to the authenticated function surface.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    make_client_fixture,
)
from runtime.api.deployment_stage_approval_fixture import (
    yield_seeded_api_db_with_default_approvals,
)
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def test_db():
    yield from yield_seeded_api_db_with_default_approvals()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


def _item_status_change_calls(mock_emit):
    return [
        c
        for c in mock_emit.call_args_list
        if c.args and c.args[0] == "ItemStatusChanged"
    ]


class TestApproveDoesNotBypassInbox:
    """The retired item route may request approval, never move item state."""

    def test_emit_fires_when_status_actually_transitions(self, client, test_db):
        # Seeded item 4 is at status='release' — seed a sibling item under
        # the same run so we can drive a transition from 'implemented' to
        # 'release' through the run-member loop.
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (8, 'sibling member', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'implemented', 'medium',
                       1, 8, '2026-03-01T00:00:00Z',
                       '2026-03-01T00:00:00Z', 'user',
                       'approve-deploy', 'test-approval-flow')"""
        )
        conn.execute(
            """INSERT INTO deployment_run_items (run_id, item_id, added_at)
               VALUES ('run-20260325-001', 8, '2026-03-25T00:00:00Z')"""
        )
        conn.commit()
        conn.close()

        with patch("yoke_core.domain.backlog_rendering._emit_event") as mock_emit:
            resp = client.post("/v1/items/4/approve", json={})

        assert resp.status_code == 409
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == []

    def test_emit_skipped_when_already_at_release(self, client, test_db):
        # Seeded item 4 is already at status='release'. Approving it
        # advances deploy_stage but does not transition status, so the
        # canonical emit MUST stay quiet.
        with patch("yoke_core.domain.backlog_rendering._emit_event") as mock_emit:
            resp = client.post("/v1/items/4/approve", json={})

        assert resp.status_code == 409
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == [], (
            f"approval of an already-release item must not emit "
            f"ItemStatusChanged; got {mock_emit.call_args_list}"
        )


class TestPatchStatusBoundary:
    """PATCH status writes are denied and therefore never emit."""

    def test_status_transition_is_denied_without_emit(self, client, test_db):
        # Item 1 is at status='implementing' per the test fixture seed.
        # The route must reject even a workflow-valid lifecycle hop.
        with patch("yoke_core.domain.backlog_rendering._emit_event") as mock_emit:
            resp = client.patch(
                "/v1/items/1",
                json={"status": "implemented"},
            )

        assert resp.status_code == 409, resp.text
        assert resp.json()["error"]["code"] == "STATUS_UPDATE_REQUIRES_LIFECYCLE"
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == []

    def test_emit_skipped_for_non_status_patch(self, client, test_db):
        # Patch only priority — no status field in the request, so no
        # ItemStatusChanged emit.
        with patch("yoke_core.domain.backlog_rendering._emit_event") as mock_emit:
            resp = client.patch(
                "/v1/items/1",
                json={"priority": "low"},
            )

        assert resp.status_code == 200
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == [], (
            f"priority-only patch must not emit ItemStatusChanged; "
            f"got {mock_emit.call_args_list}"
        )

    def test_emit_skipped_for_same_status_patch(self, client, test_db):
        # Patch status to the SAME value the item already has — no
        # transition, no emit. The patch may be accepted or rejected by
        # the mutation-layer gate; in either case the emit must stay
        # quiet because there is no real transition.
        with patch("yoke_core.domain.backlog_rendering._emit_event") as mock_emit:
            resp = client.patch(
                "/v1/items/1",
                json={"status": "implementing"},
            )

        assert resp.status_code == 409
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == [], (
            f"same-status patch must not emit ItemStatusChanged; "
            f"got {mock_emit.call_args_list}"
        )
