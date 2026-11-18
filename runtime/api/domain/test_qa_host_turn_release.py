"""Releasing a reserved QA host turn ends the waiting execution it was held for.

The measured miss (run-20261118-030): two member executions sat ``waiting``
for over two hours after their reserved host turns were released. The open
execution still counted as a walk, so upkeep skipped the member while the
fleet report said "driver gone; upkeep sends it". The wakes went out within
seconds of each execution being aborted by hand.
"""

from __future__ import annotations

from uuid import uuid4

from runtime.api.domain.qa_host_turns_test_support import MACHINE, _notices
from runtime.api.domain.test_deployment_qa_driverless_wake import (
    MEMBERS,
    RUN_ID,
    _held_key,
    _seed,
    _wait_keys,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE
from runtime.api.steering_fleet_test_helpers import (
    PROJECT_ID,
    WORKER_SESSION,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.deployment_qa_driverless_wake import wake_driverless_qa_waits
from yoke_core.domain.deployment_qa_stage_wake_state import member_wake_states
from yoke_core.domain.qa_host_turns import join_host_line, reserve_host_turn
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MEMBER = MEMBERS[0]
DRIVERLESS = "wake pending (driver gone; the next control-plane upkeep pass sends it)"


def _waiting_member_execution(conn) -> str:
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,%s,%s,'1',%s,'[]',0,'waiting',now(),now())",
        (execution_id, RUN_ID, ITEM_QA_STAGE, MEMBER, WORKER_SESSION, roster_digest([])),
    )
    join_host_line(
        conn,
        make_qa_admission_target(MACHINE),
        session_id=WORKER_SESSION,
        actor_id=1,
        resume_command="unused for plan executions",
        execution_id=execution_id,
    )
    conn.commit()
    return execution_id


def _execution(conn, execution_id: str):
    return conn.execute(
        "SELECT state, release_reason FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()


def _report(conn) -> dict[int, str]:
    return member_wake_states(
        conn,
        run_id=RUN_ID,
        stage_name=ITEM_QA_STAGE,
        item_ids=list(MEMBERS),
        project_id=PROJECT_ID,
        driver_live=False,
    )


def test_released_reservation_aborts_the_waiting_execution_and_upkeep_wakes_it(
    test_db, monkeypatch
) -> None:
    conn = _seed(seed_steering_scope(test_db))
    execution_id = _waiting_member_execution(conn)
    _notices(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    reserve_host_turn(conn, target)
    conn.commit()
    reservation = active_claim(conn, target)
    assert reservation.session_id == WORKER_SESSION

    # While the walk is open, upkeep skips the member and the report agrees.
    assert _report(conn)[MEMBER] == f"walking under session {WORKER_SESSION}"
    assert wake_driverless_qa_waits(conn)["sent"] == [
        f"{RUN_ID}:{ITEM_QA_STAGE}:{MEMBERS[1]}"
    ]

    release(conn, reservation.id, "not needed")

    state, reason = _execution(conn, execution_id)
    assert state == "aborted"
    assert reason.startswith("qa_host_turn_released: ")
    assert f"QA host {MACHINE}" in reason
    assert f"yoke qa plan run --item YOK-{MEMBER} --stage {ITEM_QA_STAGE}" in reason
    assert active_claim(conn, target) is None
    assert _report(conn)[MEMBER] == DRIVERLESS

    assert wake_driverless_qa_waits(conn) == {
        "sent": [f"{RUN_ID}:{ITEM_QA_STAGE}:{MEMBER}"],
        "errors": [],
    }
    assert _held_key(MEMBER) in _wait_keys(conn)


def test_release_keeps_an_execution_still_queued_on_another_host(
    test_db, monkeypatch
) -> None:
    conn = _seed(seed_steering_scope(test_db))
    execution_id = _waiting_member_execution(conn)
    _notices(monkeypatch)
    target = make_qa_admission_target(MACHINE)
    reserve_host_turn(conn, target)
    conn.commit()
    other = make_qa_admission_target("other-lab")
    seed_session(conn, "someone-else")
    acquire(conn, other, "someone-else")
    join_host_line(
        conn,
        other,
        session_id=WORKER_SESSION,
        actor_id=1,
        resume_command="unused for plan executions",
        execution_id=execution_id,
    )
    conn.commit()

    release(conn, active_claim(conn, target).id, "not needed")

    assert _execution(conn, execution_id)[0] == "waiting"
    assert _report(conn)[MEMBER] == f"walking under session {WORKER_SESSION}"
