"""Removing a release member settles its cursors and every queued host turn."""

import json
from unittest import mock
from uuid import uuid4

import pytest
import psycopg

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_deployment_qa_stage_member_removal import (
    REMOVED,
    REMAINING,
    RUN,
    _ready_run,
)
from runtime.api.domain.test_qa_host_turns import _notices
from runtime.api.domain.deployment_member_qa_authorization_test_support import _entry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removal,
)
from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_abort
from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
from yoke_core.domain.qa_host_turns import (
    HOST_WAIT_KIND,
    queued_host_turns,
    reserve_host_turn,
)
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.deployment_runs_lock import lock_run
from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


def _execution(
    conn, *, member=REMOVED, state="waiting", stage="item-qa", session="removed-qa"
):
    execution = str(uuid4())
    wait = (
        json.dumps(
            {
                "kind": HOST_WAIT_KIND,
                "machine": "linux-lab",
                "queued_at": "2026-10-01T10:00:00Z",
                "resume_command": "resume QA",
            }
        )
        if state == "waiting"
        else None
    )
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at,release_reason) "
        "VALUES(%s,%s,%s,%s,%s,'2',%s,'[]',0,%s,%s,%s,%s)",
        (
            execution,
            RUN,
            stage,
            member,
            session,
            roster_digest([]),
            state,
            "2026-10-01T10:00:00Z",
            "2026-10-01T10:00:00Z",
            wait,
        ),
    )
    conn.commit()
    return execution


def _state(conn, execution):
    return dict(
        conn.execute(
            "SELECT state,machine_lease_id,release_reason FROM qa_plan_executions WHERE id=%s",
            (execution,),
        ).fetchone()
    )


@pytest.mark.parametrize("state", ["waiting", "active", "awaiting_agent_review"])
def test_removal_aborts_live_cursor_and_releases_reserved_or_attached_host(
    test_db, monkeypatch, state
):
    _ready_run(test_db)
    seed_qa_session(test_db, "removed-qa", "remaining-qa")
    _notices(monkeypatch)
    target = make_qa_admission_target("linux-lab")
    execution = _execution(test_db, state=state)
    if state == "waiting":
        reserve_host_turn(test_db, target)
        test_db.commit()
        lease = active_claim(test_db, target)
    else:
        lease = acquire(test_db, target, "removed-qa")
        test_db.execute(
            "UPDATE qa_plan_executions SET machine_lease_id=%s WHERE id=%s",
            (lease.id, execution),
        )
        test_db.commit()
    other = _execution(
        test_db, member=REMAINING, session="remaining-qa", stage="next-qa"
    )
    remove_member_on(test_db, RUN, REMOVED, reason="QA waits for another release")
    test_db.commit()
    assert _state(test_db, execution) == {
        "state": "aborted",
        "machine_lease_id": None,
        "release_reason": "deployment-member-removed",
    }
    assert _state(test_db, other)["state"] == "waiting"
    assert active_claim(test_db, target).session_id == "remaining-qa"
    assert test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (lease.id,)
    ).fetchone()[0]


def test_removal_is_atomic_and_cannot_regrant_another_cursor_of_removed_member(
    test_db, monkeypatch
):
    _ready_run(test_db)
    seed_qa_session(test_db, "removed-qa", "removed-other", "host-owner")
    _notices(monkeypatch)
    target = make_qa_admission_target("linux-lab")
    lease = acquire(test_db, target, "host-owner")
    first = _execution(test_db)
    second = _execution(test_db, stage="later-qa", session="removed-other")
    remove_member_on(test_db, RUN, REMOVED, reason="blocked QA")
    assert _state(test_db, first)["state"] == "aborted"
    assert _state(test_db, second)["state"] == "aborted"
    test_db.rollback()
    assert _state(test_db, first)["state"] == "waiting"
    assert _state(test_db, second)["state"] == "waiting"
    assert test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, REMOVED),
    ).fetchone()
    remove_member_on(test_db, RUN, REMOVED, reason="blocked QA")
    test_db.commit()
    release(test_db, lease.id, "host free")
    assert not queued_host_turns(test_db, "linux-lab")
    assert active_claim(test_db, target) is None


def _request(execution, *, function="qa.plan_execution.abort", session="removed-qa"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="2", session_id=session),
        target=TargetRef(
            kind="deployment_run", deployment_run_id=RUN, project_id="yoke"
        ),
        payload={"execution_id": execution, "reason": "removed member residue"},
    )


def test_removed_holder_can_abort_legacy_residue_but_cannot_continue_it(test_db):
    _ready_run(test_db)
    seed_qa_session(test_db, "removed-qa", messageable=True)
    execution = _execution(test_db)
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, REMOVED),
    )
    record_membership_removal(
        test_db, RUN, REMOVED, reason="old removal", session_id=None, actor_id=2
    )
    test_db.commit()
    request = _request(execution)
    assert resolve_run_qa_subject(test_db, request)[2] == REMOVED
    assert (
        check_dispatch_permission(test_db, _entry(request.function), request).error
        is None
    )
    with mock.patch(
        "yoke_core.domain.yoke_function_dispatch_claims.who_claims_for_item",
        return_value={"id": 17, "session_id": "removed-qa"},
    ):
        assert qa_subject_claim_verdict(request)[0]
        assert not qa_subject_claim_verdict(_request(execution, session="outsider"))[0]
    result = handle_plan_execution_abort(request)
    assert result.primary_success
    assert _state(test_db, execution)["state"] == "aborted"
    assert handle_plan_execution_abort(request).primary_success  # Idempotent cleanup.
    with pytest.raises(ValueError, match="not an attached member"):
        resolve_run_qa_subject(
            test_db, _request(execution, function="qa.plan_execution.heartbeat")
        )


def test_unrecorded_missing_member_does_not_gain_abort_authority(test_db):
    _ready_run(test_db)
    execution = _execution(test_db)
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, REMOVED),
    )
    test_db.commit()
    with pytest.raises(ValueError, match="not an attached member"):
        resolve_run_qa_subject(test_db, _request(execution))


def test_member_admission_serializes_with_removal_and_refuses_after_commit(test_db):
    _ready_run(test_db)
    lock_item_workflow_bindings(test_db, (REMOVED,))
    lock_run(test_db, RUN)
    remove_member_on(test_db, RUN, REMOVED, reason="concurrent QA admission")
    with connect_test_database(test_db.info.dbname) as other:
        other.execute("SET LOCAL lock_timeout='100ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            begin_plan_execution(
                other,
                deployment_run_id=RUN,
                deployment_stage="item-qa",
                deployment_member_item_id=REMOVED,
                actor_id="2",
                session_id="removed-qa",
            )
        other.rollback()
        test_db.commit()
        with pytest.raises(ValueError, match="no longer attached"):
            begin_plan_execution(
                other,
                deployment_run_id=RUN,
                deployment_stage="item-qa",
                deployment_member_item_id=REMOVED,
                actor_id="2",
                session_id="removed-qa",
            )


def test_terminal_cursor_history_survives_member_removal(test_db):
    _ready_run(test_db)
    execution = _execution(test_db, state="completed")
    remove_member_on(test_db, RUN, REMOVED, reason="next release")
    test_db.commit()
    assert _state(test_db, execution)["state"] == "completed"
