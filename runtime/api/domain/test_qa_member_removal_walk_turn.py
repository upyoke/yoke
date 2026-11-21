"""A removed member's live mission walk keeps its reserved host turn until walk end.

The measured miss (feedback 97827, run-20261120-017): removing a member
cancelled its walking execution's waits and released its reserved turn on
windows-native-lab while the walk still drove a Stage plan there; the next
waiter ran its restore and baseline under the live walk.
"""

from __future__ import annotations

import json
from uuid import uuid4

from runtime.api.domain.qa_host_turns_test_support import MACHINE, _notices
from runtime.api.domain.test_deployment_qa_driverless_wake import MEMBERS, RUN_ID, _seed
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE
from runtime.api.steering_fleet_test_helpers import (
    WORKER_SESSION,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain import deployment_member_removal_notice
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.deployment_run_member_removal import remove_member_on
from yoke_core.domain.qa_host_turns import join_host_queue, reserve_host_turn
from yoke_core.domain.qa_plan_execution_abort_reason import MEMBER_REMOVED_REASON
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.work_claim_targets import make_qa_admission_target

REMOVED, OTHER = MEMBERS[0], MEMBERS[1]
NEXT_SESSION = "next-waiter-session"
# A mission that declares no Test Machine, like 2111c2e8's shared-host-power case.
WALK_ROSTER = [{"runner_id": "agent_mission", "requirement_id": 1}]


def _execution(conn, member: int, session: str, state: str, roster: list) -> str:
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,%s,%s,'1',%s,%s,0,%s,now(),now())",
        (
            execution_id,
            RUN_ID,
            ITEM_QA_STAGE,
            member,
            session,
            roster_digest(roster),
            json.dumps(roster),
            state,
        ),
    )
    join_host_queue(
        conn,
        make_qa_admission_target(MACHINE),
        session_id=session,
        actor_id=1,
        resume_command="unused for plan executions",
        execution_id=execution_id,
    )
    conn.commit()
    return execution_id


def _wait_states(conn, execution_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT state FROM qa_test_machine_waits WHERE qa_plan_execution_id=%s",
        (execution_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _queued_behind_a_reserved_turn(conn, *, walk_state: str):
    target = make_qa_admission_target(MACHINE)
    removed = _execution(conn, REMOVED, WORKER_SESSION, walk_state, WALK_ROSTER)
    reserve_host_turn(conn, target)
    conn.commit()
    seed_session(conn, NEXT_SESSION)
    waiter = _execution(conn, OTHER, NEXT_SESSION, "waiting", [])
    assert active_claim(conn, target).session_id == WORKER_SESSION
    return target, removed, waiter


def _record_notices(monkeypatch) -> dict[int, bool]:
    pending: dict[int, bool] = {}
    original = deployment_member_removal_notice.notify_removed_member

    def notify(conn, **kwargs):
        pending[kwargs["item_id"]] = kwargs["host_cleanup_pending"]
        return original(conn, **kwargs)

    monkeypatch.setattr(deployment_member_removal_notice, "notify_removed_member", notify)
    return pending


def test_removal_keeps_a_walking_executions_reserved_turn_until_walk_end(
    test_db, monkeypatch
) -> None:
    conn = _seed(seed_steering_scope(test_db))
    _notices(monkeypatch)
    pending = _record_notices(monkeypatch)
    target, removed, waiter = _queued_behind_a_reserved_turn(conn, walk_state="walking")

    remove_member_on(conn, RUN_ID, REMOVED, reason="taken over by a newer run")
    conn.commit()

    walk = lock_plan_execution(conn, removed)
    conn.rollback()
    assert walk["state"] == "walking"
    assert abort_request(walk)["reason"] == MEMBER_REMOVED_REASON
    assert _wait_states(conn, removed) == ["reserved"]
    assert active_claim(conn, target).session_id == WORKER_SESSION
    assert _wait_states(conn, waiter) == ["waiting"]
    assert pending == {REMOVED: True}

    # Walk end finishes the stopped walk and only then serves the next waiter.
    finish_plan_execution(
        conn,
        lock_plan_execution(conn, removed),
        state="aborted",
        reason=MEMBER_REMOVED_REASON,
        commit=False,
    )
    conn.commit()
    ended = lock_plan_execution(conn, removed)
    conn.rollback()
    assert ended["state"] == "aborted"
    assert _wait_states(conn, removed) == ["cancelled"]
    assert active_claim(conn, target).session_id == NEXT_SESSION
    assert _wait_states(conn, waiter) == ["reserved"]


def test_removal_returns_a_waiting_executions_turn_at_once(test_db, monkeypatch) -> None:
    conn = _seed(seed_steering_scope(test_db))
    _notices(monkeypatch)
    pending = _record_notices(monkeypatch)
    target, removed, waiter = _queued_behind_a_reserved_turn(conn, walk_state="waiting")

    remove_member_on(conn, RUN_ID, REMOVED, reason="taken over by a newer run")
    conn.commit()

    stopped = lock_plan_execution(conn, removed)
    conn.rollback()
    assert stopped["state"] == "aborted"
    assert _wait_states(conn, removed) == ["cancelled"]
    assert active_claim(conn, target).session_id == NEXT_SESSION
    assert _wait_states(conn, waiter) == ["reserved"]
    assert pending == {REMOVED: False}
