"""An item's work approvals read where they stand against the item now.

The item page and the run card read one record per request. A request for
the item's current transition is pending, approved or rejected; once its
transition consumed it, completed; a request whose transition the item has
since left — reopened work, a re-pinned workflow — is superseded and never
reads as approving the work as it stands.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_independent_member_delivery_close_out import MEMBER_A
from runtime.api.domain.test_member_done_approval_close_out import (
    RUN_ID,
    _approval_members,
    _done_request,
    _owner,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.decision_gate_record import lifecycle_standing
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.deployment_run_gates import run_gates
from yoke_core.domain.item_lifecycle_approvals import item_approval_gates

ITEM = {"status": "release", "workflow_id": "dash", "workflow_version_id": 7}


def _request(**facts: Any) -> dict[str, Any]:
    context = {
        "from_stage": "release",
        "to_stage": "done",
        "workflow_id": "dash",
        "workflow_version_id": 7,
    }
    return {"status": "resolved", "resolution_action": "approve", "consumed_at": None,
            "subject_context": context, **facts}


def test_standing_follows_the_items_current_transition() -> None:
    assert lifecycle_standing(_request(status="pending"), ITEM) == "pending"
    assert lifecycle_standing(_request(), ITEM) == "approved"
    assert lifecycle_standing(_request(resolution_action="reject"), ITEM) == "rejected"
    done = {**ITEM, "status": "done"}
    assert lifecycle_standing(_request(consumed_at="2026-10-23"), done) == "completed"


def test_an_answer_for_a_transition_the_item_left_is_superseded() -> None:
    reopened = {**ITEM, "status": "implementing"}
    assert lifecycle_standing(_request(consumed_at="2026-10-23"), reopened) == "superseded"
    assert lifecycle_standing(_request(), reopened) == "superseded"
    repinned = {**ITEM, "workflow_version_id": 8}
    assert lifecycle_standing(_request(status="pending"), repinned) == "superseded"
    assert lifecycle_standing(_request(status="withdrawn"), ITEM) == "superseded"
    assert lifecycle_standing(_request(), None) == "superseded"


def test_item_page_and_run_card_read_the_same_decision(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A)
    owner = _owner(test_db)
    request_id = int(_done_request(test_db, MEMBER_A)["id"])

    [item_gate] = item_approval_gates(test_db, MEMBER_A, actor_id=owner)
    run_gate = next(
        gate
        for gate in run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID]
        if gate["request_id"] == request_id
    )
    assert item_gate == run_gate
    assert item_gate["standing"] == "pending"
    assert item_gate["can_act"] is True
    assert item_approval_gates(test_db, MEMBER_A, actor_id=None)[0]["can_act"] is False

    resolve_decision_request(test_db, request_id, actor_id=owner, action="approve")

    [completed] = item_approval_gates(test_db, MEMBER_A, actor_id=owner)
    assert completed["standing"] == "completed"
    assert completed["consumed_at"] is not None
    assert completed["resolved_by"]
    assert completed["can_act"] is False
