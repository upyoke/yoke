"""Canonical approval preflight parity and consumption behavior."""

from __future__ import annotations

from runtime.api.domain.status_transition_preflight_test_support import (
    TARGET_STATUS as TARGET_STATUS,
    _actor_id as _actor_id,
    _approval_definition as _approval_definition,
    _isolate_status_effects as _isolate_status_effects,
    _publish_approval_workflow as _publish_approval_workflow,
    _request as _request,
)


from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import (
    backlog,
    backlog_update_op,
)
from yoke_core.domain.handlers.items_scalar import handle_scalar_update
from yoke_core.domain.handlers.lifecycle_transition import handle_transition


def test_default_only_approval_is_create_once_and_resolves_on_both_handlers(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Default approval parity",
        enabled=True,
    )
    actor_id = _actor_id(test_db)
    insert_item(test_db, id=961, workflow_id="issue", status="idea")
    insert_item(test_db, id=962, workflow_id="issue", status="idea")
    calls = (
        (961, handle_transition, True, "approval_required"),
        (962, handle_scalar_update, False, "lifecycle_gate_unmet"),
    )

    for item_id, handler, lifecycle, expected_code in calls:
        request = _request(
            item_id=item_id,
            actor_id=actor_id,
            lifecycle=lifecycle,
        )
        first = handler(request)
        repeated = handler(request)
        assert first.primary_success is False
        assert repeated.primary_success is False
        assert first.error is not None
        assert first.error.code == expected_code
        rows = test_db.execute(
            "SELECT id FROM decision_requests "
            "WHERE subject_type='item_transition' AND subject_key=%s",
            (f"{item_id}:{TARGET_STATUS}",),
        ).fetchall()
        assert len(rows) == 1
        test_db.execute(
            "UPDATE decision_requests SET status='resolved', "
            "resolution_action='approve', resolved_at=NOW() "
            "WHERE id=%s",
            (int(rows[0][0]),),
        )
        test_db.commit()
        passed = handler(request)
        assert passed.primary_success is True

    statuses = test_db.execute(
        "SELECT id, status FROM items WHERE id IN (961, 962) ORDER BY id"
    ).fetchall()
    assert [(int(row[0]), str(row[1])) for row in statuses] == [
        (961, TARGET_STATUS),
        (962, TARGET_STATUS),
    ]


def test_consumed_approval_cannot_authorize_reentry(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Approval consumption",
        enabled=True,
    )
    item_id = 972
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")

    first = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        originator_actor_id=_actor_id(test_db),
    )
    assert first["error_code"] == "GATE_APPROVAL_REQUIRED"
    first_request_id = int(
        test_db.execute(
            "SELECT id FROM decision_requests WHERE subject_key=%s",
            (f"{item_id}:{TARGET_STATUS}",),
        ).fetchone()[0]
    )
    test_db.execute(
        "UPDATE decision_requests SET status='resolved', "
        "resolution_action='approve', resolved_at=NOW() WHERE id=%s",
        (first_request_id,),
    )
    test_db.commit()

    approved = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        originator_actor_id=_actor_id(test_db),
    )
    assert approved["success"] is True
    consumed = test_db.execute(
        "SELECT consumed_at, consumed_from_stage, consumed_to_stage "
        "FROM decision_requests WHERE id=%s",
        (first_request_id,),
    ).fetchone()
    assert consumed[0] is not None
    assert (str(consumed[1]), str(consumed[2])) == (
        "idea",
        TARGET_STATUS,
    )

    test_db.execute(
        "UPDATE items SET status='idea' WHERE id=%s",
        (item_id,),
    )
    test_db.commit()
    replay = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        originator_actor_id=_actor_id(test_db),
    )
    assert replay["error_code"] == "GATE_APPROVAL_REQUIRED"
    requests = test_db.execute(
        "SELECT id, status, consumed_at FROM decision_requests "
        "WHERE subject_key=%s ORDER BY id",
        (f"{item_id}:{TARGET_STATUS}",),
    ).fetchall()
    assert len(requests) == 2
    assert int(requests[0][0]) == first_request_id
    assert requests[0][2] is not None
    assert (str(requests[1][1]), requests[1][2]) == ("pending", None)


def test_resolved_approval_holds_parent_lock_through_authoritative_gate(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Resolved approval lock release",
        enabled=True,
    )
    item_id = 963
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    first = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        originator_actor_id=_actor_id(test_db),
    )
    assert first["error_code"] == "GATE_APPROVAL_REQUIRED"
    test_db.execute(
        "UPDATE decision_requests SET status='resolved', "
        "resolution_action='approve', resolved_at=NOW() "
        "WHERE subject_key=%s",
        (f"{item_id}:{TARGET_STATUS}",),
    )
    test_db.commit()

    gate_saw_locked_connection = False

    def lock_item_in_gate(*, conn, **_kwargs):
        nonlocal gate_saw_locked_connection
        conn.execute(
            "SELECT id FROM items WHERE id=%s FOR UPDATE NOWAIT",
            (item_id,),
        ).fetchone()
        gate_saw_locked_connection = True
        return None

    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        lock_item_in_gate,
    )
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value=TARGET_STATUS,
        force=True,
        no_github=True,
        originator_actor_id=_actor_id(test_db),
    )
    assert result["success"] is True
    assert gate_saw_locked_connection is True
