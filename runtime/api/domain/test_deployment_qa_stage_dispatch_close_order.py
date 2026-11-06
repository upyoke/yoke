"""An item-QA stage wakes every waiting member before any close-out.

A close-out can take minutes (mostly its acceptance reads). Closing each
accepted member inline held every later member's wake behind it. The walk
now gates and wakes every member, committing each accepted member's stage
result, then closes the accepted members in the same pass.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_stage_dispatch_close_order_test_support import (
    MEMBER_SEQUENCES as MEMBER_SEQUENCES,
    PROJECT_SLUG as PROJECT_SLUG,
    PUBLIC_PREFIX as PUBLIC_PREFIX,
    RUN_ID as RUN_ID,
    SETTLED_MEMBER as SETTLED_MEMBER,
    STAGE as STAGE,
    WAITING_MEMBER as WAITING_MEMBER,
    _Conn as _Conn,
    _Rows as _Rows,
    _status as _status,
)


from unittest.mock import patch

from yoke_contracts.public_ref import format_item_ref

from yoke_core.domain import deployment_qa_dispatch_wait_notice as wait_notice
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch
from yoke_core.domain import deployment_qa_dispatch_gating as gating
from yoke_core.domain import deployment_qa_stage_gate as gate


def test_every_waiting_member_wakes_before_an_accepted_member_closes() -> None:
    events: list[tuple[str, int]] = []
    conn = _Conn()
    with (
        patch("yoke_core.domain.deployment_qa_dispatch_settled.settled_member_status", return_value=None),
        patch.object(gate, "deployment_qa_stage_status", side_effect=_status),
        patch.object(gating, "report_stage_result"),
        patch.object(
            wait_notice,
            "notify_item_scoped_qa_wait",
            side_effect=lambda conn, **kw: (
                events.append(("wake", kw["item_id"])) or "delivered"
            ),
        ),
        patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice."
            "notify_items_qa_accepted",
            side_effect=lambda conn, **kw: events.extend(
                ("close", item_id) for item_id in kw["item_ids"]
            ),
        ),
    ):
        code, message = dispatch.materialize_and_gate_deployment_qa_stage(
            conn, STAGE, run_id=RUN_ID
        )

    assert code == -4
    member_ref = format_item_ref(
        PROJECT_SLUG, PUBLIC_PREFIX, MEMBER_SEQUENCES[WAITING_MEMBER]
    )
    assert f"member {member_ref}" in message
    assert f"member {WAITING_MEMBER}" not in message
    # The settled member sorts first, yet the later member's wake goes first.
    assert events == [("wake", WAITING_MEMBER), ("close", SETTLED_MEMBER)]
    assert conn.commits >= 2


def test_a_later_member_error_still_closes_members_accepted_before_it() -> None:
    def failing(conn, *, member_item_id, **kw):
        if member_item_id == WAITING_MEMBER:
            raise ValueError("pinned plan is invalid")
        return _status(conn, member_item_id=member_item_id, **kw)

    closed: list[int] = []
    conn = _Conn()
    with (
        patch("yoke_core.domain.deployment_qa_dispatch_settled.settled_member_status", return_value=None),
        patch.object(gate, "deployment_qa_stage_status", side_effect=failing),
        patch.object(gating, "removed_item_ids", return_value=set()),
        patch.object(gating, "report_stage_result"),
        patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice."
            "notify_items_qa_accepted",
            side_effect=lambda conn, **kw: closed.extend(kw["item_ids"]),
        ),
    ):
        code, message = dispatch.materialize_and_gate_deployment_qa_stage(
            conn, STAGE, run_id=RUN_ID
        )

    assert (code, message) == (1, "pinned plan is invalid")
    assert closed == [SETTLED_MEMBER]
    # The failed member's uncommitted work is discarded before close-out commits.
    assert conn.rollbacks == 1


def test_the_gate_leaves_acceptance_to_a_caller_that_defers_it() -> None:
    accepted = {"accepted": True, "reasons": []}
    with (
        patch("yoke_core.domain.deployment_qa_dispatch_settled.settled_member_status", return_value=None),
        patch.object(gate, "deployment_qa_stage_subject", return_value={}),
        patch.object(gate, "deployment_qa_execution_target", return_value={}),
        patch(
            "yoke_core.domain.deployment_qa_target_continuity.settlement_target",
            side_effect=lambda conn, subject, target: target,
        ),
        patch.object(gate.target_authority, "target_digest", return_value="d"),
        patch.object(gate, "_settle_stage_status", return_value=dict(accepted)),
        patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice."
            "notify_item_qa_accepted"
        ) as notify,
    ):
        kwargs = {"run_id": RUN_ID, "stage_name": "item-qa"}
        gate.deployment_qa_stage_status(
            None, member_item_id=SETTLED_MEMBER, notify_acceptance=False, **kwargs
        )
        notify.assert_not_called()
        gate.deployment_qa_stage_status(None, member_item_id=SETTLED_MEMBER, **kwargs)
        notify.assert_called_once()
