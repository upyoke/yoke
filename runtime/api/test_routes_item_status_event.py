"""Regression tests for YOK-1704 task 5: HTTP routes that mutate
``items.status`` must emit ``ItemStatusChanged``.

Two routes historically bypassed ``backlog.execute_update`` (the canonical
emitter) and wrote status directly:

- ``POST /v1/items/{id}/approve`` (``yoke_core.api.routes.items_approve``):
  every UPDATE drives the item to ``status='release'``. Without the fix,
  the lifecycle ledger sees no event for that transition and
  ``HC-lifecycle-continuity`` records a violation.

- ``PATCH /v1/items/{id}`` (``yoke_core.api.routes.items_write``): callers
  can patch any subset of fields including ``status``; the route batches
  field writes into one UPDATE statement.

The fix routes both through the canonical emission helper
``yoke_core.domain.backlog_rendering._emit_event``. Tests assert the
emit fires on a real transition AND does not fire when the item is
already at the target status (idempotency).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    make_client_fixture,
    make_test_db_fixture,
)
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


def _item_status_change_calls(mock_emit):
    return [
        c for c in mock_emit.call_args_list
        if c.args and c.args[0] == "ItemStatusChanged"
    ]


class TestApproveEmitsItemStatusChanged:
    """``POST /v1/items/{id}/approve`` must emit ``ItemStatusChanged``
    when the approval transitions an item into ``status='release'``."""

    def test_emit_fires_when_status_actually_transitions(self, client, test_db):
        # Seeded item 4 is at status='release' — seed a sibling item under
        # the same run so we can drive a transition from 'implemented' to
        # 'release' through the run-member loop.
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES (8, 'sibling member', 'issue', 'implemented', 'medium',
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

        with patch(
            "yoke_core.domain.backlog_rendering._emit_event"
        ) as mock_emit:
            resp = client.post("/v1/items/4/approve", json={})

        assert resp.status_code == 200
        emit_calls = _item_status_change_calls(mock_emit)
        # Item 4 was already at 'release' so MUST NOT emit. Item 8 was at
        # 'implemented' so MUST emit a single transition event.
        assert len(emit_calls) == 1, (
            f"expected one ItemStatusChanged for the transitioning "
            f"sibling, got {mock_emit.call_args_list}"
        )
        args = emit_calls[0].args
        assert args[0] == "ItemStatusChanged"
        assert args[1] == 8
        assert args[2]["from_status"] == "implemented"
        assert args[2]["to_status"] == "release"
        assert args[2]["source"] == "items-approve"

    def test_emit_skipped_when_already_at_release(self, client, test_db):
        # Seeded item 4 is already at status='release'. Approving it
        # advances deploy_stage but does not transition status, so the
        # canonical emit MUST stay quiet.
        with patch(
            "yoke_core.domain.backlog_rendering._emit_event"
        ) as mock_emit:
            resp = client.post("/v1/items/4/approve", json={})

        assert resp.status_code == 200
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == [], (
            f"approval of an already-release item must not emit "
            f"ItemStatusChanged; got {mock_emit.call_args_list}"
        )


class TestPatchEmitsItemStatusChanged:
    """``PATCH /v1/items/{id}`` must emit ``ItemStatusChanged`` when the
    patch transitions ``status``, and stay quiet for non-status patches
    or no-op same-status patches."""

    def test_emit_fires_on_status_transition(self, client, test_db):
        # Item 1 is at status='implementing' per the test fixture seed.
        # ``implementing -> implemented`` is one of the lifecycle hops the
        # PATCH route's mutation layer accepts without a QA gate against
        # this fixture's empty qa_requirements set.
        with patch(
            "yoke_core.domain.backlog_rendering._emit_event"
        ) as mock_emit:
            resp = client.patch(
                "/v1/items/1",
                json={"status": "implemented"},
            )

        assert resp.status_code == 200, resp.text
        emit_calls = _item_status_change_calls(mock_emit)
        assert len(emit_calls) == 1, (
            f"PATCH status transition must emit exactly one "
            f"ItemStatusChanged; got {mock_emit.call_args_list}"
        )
        args = emit_calls[0].args
        assert args[0] == "ItemStatusChanged"
        assert args[1] == 1
        assert args[2]["from_status"] == "implementing"
        assert args[2]["to_status"] == "implemented"
        assert args[2]["source"] == "items-patch"

    def test_emit_skipped_for_non_status_patch(self, client, test_db):
        # Patch only priority — no status field in the request, so no
        # ItemStatusChanged emit.
        with patch(
            "yoke_core.domain.backlog_rendering._emit_event"
        ) as mock_emit:
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
        with patch(
            "yoke_core.domain.backlog_rendering._emit_event"
        ) as mock_emit:
            resp = client.patch(
                "/v1/items/1",
                json={"status": "implementing"},
            )

        assert resp.status_code in (200, 409, 422)
        emit_calls = _item_status_change_calls(mock_emit)
        assert emit_calls == [], (
            f"same-status patch must not emit ItemStatusChanged; "
            f"got {mock_emit.call_args_list}"
        )
