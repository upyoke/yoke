"""A host set waits at one place on every host and never deadlocks (YOK-5484).

The measured miss (plan 19679): a single-host clean-install case took the
matrix case's three hosts because both named the same driver, and every
requeue gave the walk a fresh place at the back of each line, so it livelocked
between busy hosts.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    _terminal_recipe,
    configure_test_machine,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.qa_host_turns_test_support import _notices
from runtime.api.domain.qa_member_machine_partitions_test_support import (
    MACHINES,
    MEMBER,
    RUN,
    SESSION,
    _begin,
    _case_begin,
    _seed,
    _seed_run,
    _stages,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire, active_claim, release
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_execution_protocol import MachineQaProtocolLeaseHeld
from yoke_core.domain.qa_host_set_turns import record_host_wait, require_host_set_turn
from yoke_core.domain.qa_host_turn_release import HOST_TURN_RELEASED_REASON
from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution
from yoke_core.domain.qa_plan_execution_reentry import pause_execution, resume_execution
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.work_claim_targets import make_qa_admission_target

A, B, C = "lab-a", "lab-b", "lab-c"


def _target(name):
    return make_qa_admission_target(name)


def _execution(conn, session_id, *, age=timedelta(0)):
    """A member walk with an empty roster, so no shared place is inherited."""
    execution_id = str(uuid4())
    created = utc_now() - age
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,'item-qa',7,%s,'1',%s,'[]',0,'active',%s,%s)",
        (execution_id, str(uuid4()), session_id, roster_digest([]), created, created),
    )
    conn.commit()
    return execution_id


def _row(conn, execution_id, *, resume=False):
    if resume:
        conn.execute(
            "UPDATE qa_plan_executions SET state='active',completed_at=NULL WHERE id=%s",
            (execution_id,),
        )
    row = query_one(conn, "SELECT * FROM qa_plan_executions WHERE id=%s", (execution_id,))
    return {**row, "roster": []}


def _waits(conn, execution_id):
    rows = conn.execute(
        "SELECT test_machine,state,queued_at FROM qa_test_machine_waits "
        "WHERE qa_plan_execution_id=%s ORDER BY test_machine,queued_at",
        (execution_id,),
    ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


def _state(conn, execution_id):
    return lock_plan_execution(conn, execution_id)["state"]


def test_busy_host_queues_the_whole_set_and_keeps_the_free_host_reserved(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True, driver=MACHINES[1])
    seed_qa_session(test_db, SESSION, "busy-host", messageable=True)
    held = acquire(test_db, _target(MACHINES[1]), "busy-host")
    execution = _begin(test_db)
    response = _case_begin(execution)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "waiting"
    assert response.result_payload["host_wait"]["test_machine"] == MACHINES[1]
    assert not execution_host_leases(test_db, execution)
    waits = _waits(test_db, execution["id"])
    # Nothing is acquired; the free host is reserved and both share one place.
    assert [(name, state) for name, state, _ in waits] == [
        (MACHINES[0], "reserved"),
        (MACHINES[1], "waiting"),
    ]
    assert waits[0][2] == waits[1][2]
    release(test_db, held.id, "ready")
    resumed = _begin(test_db)
    assert resumed["id"] == execution["id"]
    response = _case_begin(resumed)
    assert response.primary_success, response.error
    leases = execution_host_leases(test_db, resumed)
    assert [claim.target.test_machine for claim in leases] == list(MACHINES)
    assert all(claim.is_active for claim in leases)


def _seed_solo_then_matrix(conn, tmp_path, monkeypatch):
    """Plan 19679's shape: a one-host baseline, then a set case on its driver."""
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

    configure_test_machine(conn, tmp_path, monkeypatch)
    replace_test_machine_settings(
        conn,
        power_project="yoke",
        test_machine=MACHINES[1],
        settings={**TEST_MACHINE_SETTINGS, "resource_name": MACHINES[1]},
        base_settings=None,
    )
    plan = create_plan(conn, project="yoke", slug="solo-matrix", infer_target_environment=False)
    sets = {"solo": {}, "matrix": {"test_machines": list(MACHINES)}}
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "terminal-check",
                "instructions": "Run a host-specific check.",
                "expected_outcome": "The check passes.",
                "method_config": {
                    **_terminal_recipe(),
                    "test_machine": MACHINES[0],
                    **sets[key],
                },
                "entry_surface": "printf done",
                "required_completion": "complete",
                "starting_state": "baseline",
                "host_baselines": ["fresh-host"],
            }
            for position, key in enumerate(sets, 1)
        ],
    )
    insert_item(conn, id=MEMBER, project_sequence=MEMBER, workflow_id="issue", status="done")
    stages = _stages(int(plan["id"]))
    stages[1]["cases"] = {"plan_id": int(plan["id"]), "case_keys": list(sets)}
    # A run-scoped walk is one roster, like a standalone plan: no split.
    stages[1]["scope"] = "run"
    _seed_run(conn, run_id=RUN, stages=stages, members=(MEMBER + 1,), existing_members=(MEMBER,))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=None,
    )


def _solo_case_done(conn, tmp_path, monkeypatch):
    """Run plan 19679's solo case and advance the cursor to the set case."""
    _seed_solo_then_matrix(conn, tmp_path, monkeypatch)
    seed_qa_session(conn, SESSION, messageable=True)
    execution = _begin(conn, deployment_member_item_id=None)
    assert len(execution["roster"]) == 2
    response = _case_begin(execution)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready"
    current = lock_plan_execution(conn, execution["id"])
    # The solo baseline does not take the matrix case's companion host.
    assert active_claim(conn, _target(MACHINES[1])) is None
    assert not execution_host_leases(conn, current)
    case = current["roster"][0]
    advance_plan_execution(
        conn,
        current,
        ordinal=0,
        requirement_id=case["requirement_id"],
        result={"requirement_id": case["requirement_id"], "case_outcome": "pass"},
    )
    return lock_plan_execution(conn, execution["id"])


@pytest.mark.parametrize("lost", MACHINES)
def test_single_host_baseline_holds_only_its_host_then_the_set_case_takes_all(
    test_db, tmp_path, monkeypatch, lost
):
    current = _solo_case_done(test_db, tmp_path, monkeypatch)
    # A check-in before the set case is admitted owes only the solo lease.
    heartbeat_plan_execution(test_db, current)
    current = lock_plan_execution(test_db, current["id"])
    response = _case_begin(current, ordinal=1)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready"
    current = lock_plan_execution(test_db, current["id"])
    leases = execution_host_leases(test_db, current)
    assert [claim.target.test_machine for claim in leases] == list(MACHINES)
    heartbeat_plan_execution(test_db, current)
    # Once admitted, losing any one host of the set ends the case's custody.
    release(test_db, active_claim(test_db, _target(lost)).id, "taken")
    with pytest.raises(ValueError, match="test_machine_set_lease_lost"):
        heartbeat_plan_execution(test_db, lock_plan_execution(test_db, current["id"]))


def test_resume_before_set_case_admission_keeps_cursor_and_primary_lease(
    test_db, tmp_path, monkeypatch
):
    current = _solo_case_done(test_db, tmp_path, monkeypatch)
    lease_id = current["test_machine_lease_id"]
    assert lease_id is not None
    pause_execution(test_db, current, phase="checkin", cursor=1, request_id="r1", attempts=0)
    resume_execution(test_db, lock_plan_execution(test_db, current["id"]))
    current = lock_plan_execution(test_db, current["id"])
    assert (current["state"], current["cursor_ordinal"]) == ("active", 1)
    assert current["test_machine_lease_id"] == lease_id
    assert active_claim(test_db, _target(MACHINES[0])).id == lease_id


def test_moving_between_hosts_keeps_the_first_place(test_db, monkeypatch):
    _notices(monkeypatch)
    seed_qa_session(test_db, "walker", "later", "holder-a", "holder-b")
    acquire(test_db, _target(A), "holder-a")
    acquire(test_db, _target(B), "holder-b")
    walker = _execution(test_db, "walker")
    record_host_wait(test_db, _row(test_db, walker), test_machine=A, rationale="busy")
    first = _waits(test_db, walker)[0][2]
    later = _execution(test_db, "later")
    record_host_wait(test_db, _row(test_db, later), test_machine=B, rationale="busy")

    moved = record_host_wait(
        test_db, _row(test_db, walker, resume=True), test_machine=B, rationale="busy"
    )

    assert _waits(test_db, walker) == [(A, "cancelled", first), (B, "waiting", first)]
    assert moved["host_wait"]["position"] == 1


def test_opposite_host_orders_both_finish_without_deadlock(test_db, monkeypatch):
    bodies = _notices(monkeypatch)
    seed_qa_session(test_db, "s1", "s2", "za", "zb", "zc")
    za = acquire(test_db, _target(A), "za")
    zb = acquire(test_db, _target(B), "zb")
    acquire(test_db, _target(C), "zc")
    # e1 queued first, on another host; e2 then waits for the set driven by B.
    e1 = _execution(test_db, "s1", age=timedelta(minutes=5))
    record_host_wait(test_db, _row(test_db, e1), test_machine=C, rationale="busy")
    e2 = _execution(test_db, "s2")
    record_host_wait(
        test_db, _row(test_db, e2), test_machine=B, rationale="busy", test_machines=(A, B)
    )
    release(test_db, za.id, "done")
    assert [state for _, state, _ in _waits(test_db, e2)] == ["reserved", "waiting"]
    assert bodies == []  # a partial set does not wake its owner

    # e1 moves to a set driven by A: its older place takes e2's partial turn.
    record_host_wait(
        test_db,
        _row(test_db, e1, resume=True),
        test_machine=A,
        rationale="busy",
        test_machines=(A, B),
    )
    assert active_claim(test_db, _target(A)).session_id == "s1"
    assert [state for _, state, _ in _waits(test_db, e2)] == ["waiting", "waiting"]
    release(test_db, zb.id, "done")
    assert len(bodies) == 1 and f"QA host turn ready: {B}" in bodies[0]
    with pytest.raises(MachineQaProtocolLeaseHeld):
        require_host_set_turn(test_db, {"id": e2}, (A, B))
    require_host_set_turn(test_db, {"id": e1}, (A, B))
    first = [acquire(test_db, _target(name), "s1") for name in (A, B)]
    for claim in first:
        release(test_db, claim.id, "case done")
    assert len(bodies) == 2
    require_host_set_turn(test_db, {"id": e2}, (A, B))
    assert [acquire(test_db, _target(name), "s2").session_id for name in (A, B)] == [
        "s2",
        "s2",
    ]
    assert _state(test_db, e2) == "waiting"


def test_released_turn_aborts_only_when_no_live_wait_remains(test_db, monkeypatch):
    _notices(monkeypatch)
    seed_qa_session(test_db, "walker", "zb")
    zb = acquire(test_db, _target(B), "zb")
    walker = _execution(test_db, "walker")
    record_host_wait(
        test_db, _row(test_db, walker), test_machine=B, rationale="busy", test_machines=(A, B)
    )
    reserved_a = active_claim(test_db, _target(A))
    assert reserved_a.session_id == "walker"

    release(test_db, reserved_a.id, "not needed")
    assert _state(test_db, walker) == "waiting"
    release(test_db, zb.id, "done")
    reserved_b = active_claim(test_db, _target(B))
    assert reserved_b.session_id == "walker"
    release(test_db, reserved_b.id, "not needed")

    execution = lock_plan_execution(test_db, walker)
    assert execution["state"] == "aborted"
    assert HOST_TURN_RELEASED_REASON in execution["release_reason"]
