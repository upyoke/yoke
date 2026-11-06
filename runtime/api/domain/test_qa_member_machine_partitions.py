"""Multi-host member QA preserves leases, evidence scope and every obligation."""

from __future__ import annotations

from runtime.api.domain.qa_member_machine_partitions_test_support import (
    MACHINES as MACHINES,
    MEMBER as MEMBER,
    RUN as RUN,
    SESSION as SESSION,
    _begin as _begin,
    _case_begin as _case_begin,
    _seed as _seed,
)


import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
)
from yoke_core.domain.coordination_claims import acquire, release
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_state import (
    lock_plan_execution,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def test_each_host_has_its_own_execution_and_member_waits_for_both(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    first = _begin(test_db)
    assert first["remaining_requirement_count"] == 1
    assert [case["case_key"] for case in first["roster"]] == [MACHINES[0]]
    contract = _case_begin(first)
    assert contract.primary_success, contract.error
    lease_id = contract.result_payload["execution"]["lease_id"]
    assert _begin(test_db)["id"] == first["id"]
    _complete_case(test_db, lock_plan_execution(test_db, first["id"]))
    assert test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (lease_id,)
    ).fetchone()[0]
    status = deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )
    assert not status["accepted"]
    second = _begin(test_db)
    assert second["id"] != first["id"]
    assert second["remaining_requirement_count"] == 0
    assert [case["case_key"] for case in second["roster"]] == [MACHINES[1]]
    assert _begin(test_db)["id"] == second["id"]
    contract = _case_begin(second)
    assert contract.primary_success, contract.error
    assert contract.result_payload["execution"]["lease_id"] != lease_id
    _complete_case(test_db, lock_plan_execution(test_db, second["id"]))
    assert deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBER
    )["accepted"]
    assert _begin(test_db)["state"] == "completed"
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage='item-qa' AND deployment_member_item_id=%s AND method_id IS NOT NULL",
            (RUN, MEMBER),
        ).fetchone()[0]
        == 2
    )


def test_a_host_pin_cannot_drop_another_required_host(test_db, tmp_path, monkeypatch):
    _seed(test_db, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="test_machine_constraint_mismatch"):
        _begin(test_db, test_machine=MACHINES[0])
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_waiting_second_host_keeps_its_partition_and_fifo(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    _complete_case(test_db, _begin(test_db))
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session

    seed_qa_session(test_db, SESSION, "occupied-host", messageable=True)
    held = acquire(test_db, make_qa_admission_target(MACHINES[1]), "occupied-host")
    second = _begin(test_db)
    response = _case_begin(second)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "waiting"
    release(test_db, held.id, "host-free")
    resumed = _begin(test_db)
    assert resumed["id"] == second["id"] and resumed["remaining_requirement_count"] == 0
    assert _case_begin(resumed).result_payload["state"] == "ready"


def test_completed_capture_without_current_passing_evidence_is_retried(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    first = _begin(test_db)
    requirement_id = _complete_case(test_db, first)
    from runtime.api.fixtures.backlog_inserts import insert_qa_run

    insert_qa_run(
        test_db,
        qa_requirement_id=requirement_id,
        verdict="fail",
        qa_kind="plan_case",
        performed_by="worktree_run",
    )
    test_db.commit()
    retry = _begin(test_db)
    assert retry["id"] != first["id"]
    assert retry["roster"][0]["requirement_id"] == requirement_id
    assert retry["remaining_requirement_count"] == 1


def test_an_unscoped_pass_does_not_cover_a_required_host(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch)
    requirements = test_db.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND method_id IS NOT NULL ORDER BY id",
        (RUN,),
    ).fetchall()
    for row in requirements:
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,started_at,completed_at,created_at) VALUES (%s,'agent','plan_case','pass',%s,%s,%s)",
            (row[0], *(["2026-09-14T00:02:00Z"] * 3)),
        )
    test_db.commit()
    first = _begin(test_db)
    assert first["remaining_requirement_count"] == 1
    assert first["roster"][0]["case_key"] == MACHINES[0]


@pytest.mark.parametrize(
    "mission,trailing", [(False, False), (True, False), (True, True)]
)
def test_inherit_chain_holds_its_host_union_before_the_opener(
    test_db, tmp_path, monkeypatch, mission, trailing
):
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    _seed(
        test_db, tmp_path, monkeypatch, inherit=True, mission=mission, trailing=trailing
    )
    first = _begin(test_db)
    assert first["remaining_requirement_count"] == int(trailing)
    assert len(first["roster"]) == 2
    response = _case_begin(first)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, first["id"])
    leases = execution_host_leases(test_db, current)
    assert [claim.target.test_machine for claim in leases] == list(MACHINES)
    opener = current["roster"][0]
    advance_plan_execution(
        test_db,
        current,
        ordinal=0,
        requirement_id=opener["requirement_id"],
        result={"requirement_id": opener["requirement_id"], "case_outcome": "passed"},
    )
    assert _begin(test_db)["id"] == first["id"]
    response = _case_begin(current, 1)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "ready"
    assert [claim.id for claim in execution_host_leases(test_db, current)] == [
        claim.id for claim in leases
    ]
