"""Canonical approval preflight parity and consumption behavior."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import (
    backlog,
    backlog_update_op,
)
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.handlers.items_scalar import handle_scalar_update
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.workflow_registry import publish_workflow_version


TARGET_STATUS = "refining-idea"


def _approval_definition(label: str, *, enabled: bool) -> dict[str, Any]:
    definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    definition["stages"][0]["label"] = label
    definition["policies"]["path_claims"] = "optional"
    definition["policies"]["approval_defaults"] = (
        {
            TARGET_STATUS: {
                "roles": ["owner"],
                "actors": [],
            },
        }
        if enabled
        else {}
    )
    return definition


def _publish_approval_workflow(
    conn: Any,
    *,
    label: str,
    enabled: bool,
) -> dict[str, Any]:
    return publish_workflow_version(
        conn,
        workflow_id="issue",
        definition=_approval_definition(label, enabled=enabled),
    )


def _actor_id(conn: Any) -> int:
    return int(
        conn.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


def _request(
    *,
    item_id: int,
    actor_id: int,
    lifecycle: bool,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=(
            "lifecycle.transition.execute" if lifecycle else "items.scalar.update"
        ),
        actor=ActorContext(
            actor_id=str(actor_id),
            session_id=f"status-preflight-{item_id}",
        ),
        target=TargetRef(kind="item", item_id=item_id),
        payload=(
            {"target_status": TARGET_STATUS, "force": True}
            if lifecycle
            else {
                "field": "status",
                "value": TARGET_STATUS,
                "force": True,
            }
        ),
    )


def _isolate_status_effects(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test-isolation")
    monkeypatch.setattr(
        backlog_update_op,
        "run_post_db_sync",
        lambda **_kwargs: 0,
    )
    monkeypatch.setattr(
        backlog_update_op._rendering,
        "_maybe_rebuild_board",
        lambda *_args, **_kwargs: None,
    )


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
        rebuild_board=False,
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
        rebuild_board=False,
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
        rebuild_board=False,
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
        rebuild_board=False,
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
        rebuild_board=False,
        originator_actor_id=_actor_id(test_db),
    )
    assert result["success"] is True
    assert gate_saw_locked_connection is True
