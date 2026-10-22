"""A removed member's in-flight host work keeps its machine until cleanup proof."""

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_qa_member_machine_partitions import (
    MEMBER,
    RUN,
    SESSION,
    _begin,
    _case_begin,
    _seed,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import qa_plan_execution_abort_state
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.deployment_member_removal_notice import (
    HOST_CLEANUP_PENDING,
    removal_notice_body,
)
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
from yoke_core.domain.qa_deployment_run_settlement import settle_unsuccessful_run
from yoke_core.domain.qa_plan_execution_abort_reason import (
    MEMBER_REMOVED_REASON,
    member_removal_pending,
)
from yoke_core.domain.qa_plan_execution_reentry import checkin_view
from yoke_core.domain.qa_plan_execution_roster_change import checkin
from yoke_core.domain.qa_plan_execution_state import (
    finish_plan_execution,
    heartbeat_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError


@pytest.fixture
def removed_inflight(test_db, tmp_path, monkeypatch):
    _seed(test_db, tmp_path, monkeypatch)
    seed_qa_session(test_db, SESSION, messageable=True)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    current = lock_plan_execution(test_db, execution["id"])
    heartbeat_plan_execution(
        test_db, current
    )  # The runner checked in: host work began.
    remove_member_on(test_db, RUN, MEMBER, reason="taken over by a newer run")
    test_db.commit()
    return current["id"], int(current["machine_lease_id"])


def _locked(conn, execution_id):
    current = lock_plan_execution(conn, execution_id)
    conn.rollback()
    return current


def test_removal_keeps_custody_and_heartbeat_under_a_recorded_abort(
    test_db, removed_inflight
):
    execution_id, lease_id = removed_inflight
    current = _locked(test_db, execution_id)
    assert current["state"] == "active"
    assert current["machine_lease_id"] == lease_id
    assert get_claim(test_db, lease_id).is_active
    assert member_removal_pending(current)
    # Its retracted case does not refuse the check-in; the abort is reported.
    checkin(test_db, current)
    assert checkin_view(current)["abort_requested"]
    assert get_claim(test_db, lease_id).is_active


def test_release_waits_for_cleanup_proof_then_settles_as_removed(
    test_db, removed_inflight, monkeypatch
):
    execution_id, lease_id = removed_inflight
    current = lock_plan_execution(test_db, execution_id)
    with pytest.raises(QaPlanExecutionStateError, match="qa_abort_restore_required"):
        finish_plan_execution(
            test_db, current, state="aborted", reason="operator", commit=False
        )
    test_db.rollback()
    assert get_claim(test_db, lease_id).is_active
    monkeypatch.setattr(
        qa_plan_execution_abort_state, "host_cleanup_proven", lambda *_: True
    )
    current = lock_plan_execution(test_db, execution_id)
    qa_plan_execution_abort_state.settle_host_abort(test_db, current)
    test_db.commit()
    settled = _locked(test_db, execution_id)
    assert settled["state"] == "aborted"
    assert settled["release_reason"] == MEMBER_REMOVED_REASON
    assert not get_claim(test_db, lease_id).is_active


def test_run_cancellation_leaves_the_pending_abort_to_its_cleanup(
    test_db, removed_inflight
):
    execution_id, lease_id = removed_inflight
    settle_unsuccessful_run(test_db, RUN, reason="superseded")
    test_db.commit()
    current = _locked(test_db, execution_id)
    assert current["state"] == "active" and member_removal_pending(current)
    assert get_claim(test_db, lease_id).is_active


def test_the_runner_keeps_its_subject_after_membership_ends(test_db, removed_inflight):
    execution_id, _ = removed_inflight
    request = FunctionCallRequest(
        function="qa.plan_execution.heartbeat",
        actor=ActorContext(actor_id="1", session_id=SESSION),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"execution_id": execution_id},
    )
    assert resolve_run_qa_subject(test_db, request) == (1, "yoke", MEMBER)


def test_the_owner_notice_names_the_pending_host_cleanup():
    body = removal_notice_body(
        run_id=RUN,
        public_ref="YOK-1",
        reason="taken over",
        removed_by="steering",
        red=(),
        host_cleanup_pending=True,
    )
    assert body.endswith(HOST_CLEANUP_PENDING)
    assert "walk-end" in body
