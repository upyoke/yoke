"""Notification fan-out and read behavior against the owned projection."""

from __future__ import annotations

import re

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.domain.decision_request_contract import (
    DEPLOYMENT_RUN_COMPLETED,
    ITEM_BLOCK_STATE_CHANGED,
)
from yoke_core.domain.decision_request_events import append_decision_event_envelope
from yoke_core.domain.inbox_notifications import (
    dispatch_addressed_event,
    mark_all_notifications_read,
    notification_rows,
)


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        yield value


class _NoEventsReadConnection:
    """Fail a notification operation that tries to read telemetry."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, statement, parameters=()):
        if re.search(r"\b(?:FROM|JOIN)\s+events\b", statement, re.IGNORECASE):
            raise AssertionError(f"notification operation read events: {statement}")
        return self._conn.execute(statement, parameters)


def _append_deployment_event(conn, *, project_id, index: int):
    return append_decision_event_envelope(
        conn,
        "DeploymentRunSucceeded",
        actor_id=2,
        session_id="",
        project_id=project_id,
        org_id=None,
        context={"run_id": f"run-{index}"},
        created_at=f"2026-07-26T14:0{index}:00Z",
    )


def test_bulk_notification_read_preserves_hidden_project_rows(conn):
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, org_id, created_at) "
        "VALUES (11, 'hidden', 'Hidden', 'HID', 1, 'now')"
    )
    for index, project_id in enumerate((10, 11, None), 1):
        event_envelope = _append_deployment_event(
            conn, project_id=project_id, index=index
        )
        dispatch_addressed_event(
            conn,
            event_envelope=event_envelope,
            project_id=project_id,
            notification_kind=DEPLOYMENT_RUN_COMPLETED,
            event_context={"initiator_actor_id": 1},
            reason=f"run-{index} succeeded",
        )
    conn.commit()

    assert (
        mark_all_notifications_read(
            _NoEventsReadConnection(conn),
            1,
            "later",
            project_ids=[10],
        )
        == 2
    )
    remaining = notification_rows(_NoEventsReadConnection(conn), 1)
    assert [row["project_id"] for row in remaining] == [11]


def test_event_envelope_fanout_derives_exact_recipients(conn):
    deploy_event = _append_deployment_event(conn, project_id=10, index=1)
    assert (
        dispatch_addressed_event(
            conn,
            event_envelope=deploy_event,
            project_id=10,
            notification_kind=DEPLOYMENT_RUN_COMPLETED,
            event_context={
                "initiator_actor_id": 1,
                "stage_approver_actor_ids": [2, 2, 3],
            },
            reason="run-1 succeeded",
        )
        == 3
    )
    item_event = append_decision_event_envelope(
        conn,
        "ItemUnblocked",
        actor_id=None,
        session_id="",
        project_id=10,
        org_id=None,
        context={"public_ref": "YOK-9"},
        created_at="2026-07-26T14:01:00Z",
    )
    assert (
        dispatch_addressed_event(
            conn,
            event_envelope=item_event,
            project_id=10,
            notification_kind=ITEM_BLOCK_STATE_CHANGED,
            event_context={"owner_actor_id": 4},
            reason="dependency reached done",
        )
        == 1
    )
    conn.commit()

    guarded = _NoEventsReadConnection(conn)
    assert len(notification_rows(guarded, 1)) == 1
    assert len(notification_rows(guarded, 2)) == 1
    assert len(notification_rows(guarded, 3)) == 1
    assert notification_rows(guarded, 4)[0]["notification_kind"] == (
        "item_block_state_changed"
    )


def test_list_response_is_stable_when_event_and_actor_rows_change(conn):
    conn.execute(
        "INSERT INTO actor_labels "
        "(actor_id, surface, label, created_at) "
        "VALUES (2, 'display', 'Original resolver', 'now')"
    )
    envelope = _append_deployment_event(conn, project_id=10, index=2)
    dispatch_addressed_event(
        conn,
        event_envelope=envelope,
        project_id=10,
        notification_kind=DEPLOYMENT_RUN_COMPLETED,
        event_context={"initiator_actor_id": 1},
        reason="run-2 succeeded",
    )
    conn.execute(
        "UPDATE events SET event_name='ChangedTelemetry', "
        "event_outcome='failed', project_id=NULL, envelope='{}' "
        "WHERE event_id=?",
        (envelope["event_id"],),
    )
    conn.execute(
        "UPDATE actor_labels SET label='Changed later' "
        "WHERE actor_id=2 AND surface='display'"
    )

    row = notification_rows(_NoEventsReadConnection(conn), 1)[0]
    assert set(row) == {
        "id",
        "event_id",
        "notification_kind",
        "reason",
        "read_at",
        "created_at",
        "event_name",
        "project_id",
        "event_outcome",
        "event",
    }
    assert row["event_name"] == "DeploymentRunSucceeded"
    assert row["project_id"] == 10
    assert row["event_outcome"] == "completed"
    assert row["event"]["context"] == {"run_id": "run-2"}
    assert row["event"]["event_name"] == "DeploymentRunSucceeded"
