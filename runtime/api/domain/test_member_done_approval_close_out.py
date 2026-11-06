"""Approving a member's done gate retries that member's own close-out.

The member's item QA is accepted on an executing run and it owes no
post-deploy check, but its done transition waits on a human approval. The
approval answers with no driver and no owner wake; the decision's own notice
re-runs the ordinary close-out, so the member reaches done, the approval is
consumed and its claim is released — while the run stays at its stage.
"""

from __future__ import annotations

from runtime.api.domain.member_done_approval_close_out_test_support import (
    RUN_ID as RUN_ID,
    _approval_members as _approval_members,
    _done_request as _done_request,
    _owner as _owner,
)


from typing import Any

from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A,
    MEMBER_B,
    _status,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.work_claim_target_sql import scope_int_sql


def _live_claim(conn: Any, item_id: int) -> Any:
    item_scope = scope_int_sql(conn, "scope", "item_id")
    return conn.execute(
        "SELECT id FROM work_claims WHERE target_kind='item' "
        f"AND released_at IS NULL AND {item_scope}=%s",
        (item_id,),
    ).fetchone()


def _run_stage(conn: Any) -> tuple[str, str]:
    row = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s", (RUN_ID,)
    ).fetchone()
    return str(row["status"]), str(row["current_stage"])


def test_approving_the_done_gate_closes_the_member(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A)
    request = _done_request(test_db, MEMBER_A)
    assert _status(test_db, MEMBER_A) == "release"
    assert request is not None and request["status"] == "pending"

    resolve_decision_request(
        test_db, int(request["id"]), actor_id=_owner(test_db), action="approve"
    )

    assert _status(test_db, MEMBER_A) == "done"
    assert _done_request(test_db, MEMBER_A)["consumed_at"] is not None
    assert _live_claim(test_db, MEMBER_A) is None
    assert _status(test_db, MEMBER_B) == "release"
    assert _run_stage(test_db) == ("executing", "item-qa")


def test_rejecting_the_done_gate_leaves_the_member_held(test_db, monkeypatch) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A)
    request = _done_request(test_db, MEMBER_A)

    resolve_decision_request(
        test_db, int(request["id"]), actor_id=_owner(test_db), action="reject"
    )

    assert _status(test_db, MEMBER_A) == "release"
    assert _live_claim(test_db, MEMBER_A) is not None


def test_a_sibling_open_approval_does_not_hold_the_member(
    test_db, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _approval_members(test_db, MEMBER_A, MEMBER_B)
    request = _done_request(test_db, MEMBER_A)

    resolve_decision_request(
        test_db, int(request["id"]), actor_id=_owner(test_db), action="approve"
    )

    assert _status(test_db, MEMBER_A) == "done"
    assert _status(test_db, MEMBER_B) == "release"
    assert _done_request(test_db, MEMBER_B)["status"] == "pending"
    assert _live_claim(test_db, MEMBER_B) is not None
