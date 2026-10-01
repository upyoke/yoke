"""Simultaneous host acquisition retains both FIFO leases without deadlock."""

from unittest import mock

import pytest

from runtime.api.domain.test_qa_member_machine_partitions import (
    MACHINES,
    SESSION,
    _begin,
    _case_begin,
    _seed,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from yoke_core.domain.coordination_claims import acquire, release
from yoke_core.domain.machine_qa_case_hosts import normalize_config_machines
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    finish_plan_execution,
    heartbeat_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_host_leases import (
    execution_host_leases,
    require_case_host_leases,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target


def test_case_holds_both_hosts_and_releases_them_after_completion(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True, driver=MACHINES[1])
    execution = _begin(test_db)
    assert execution["remaining_requirement_count"] == 0
    response = _case_begin(execution)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, execution["id"])
    leases = execution_host_leases(test_db, current)
    assert [claim.target.machine_id for claim in leases] == list(MACHINES)
    assert response.result_payload["execution"]["lease_id"] == leases[1].id
    assert _case_begin(current).primary_success
    require_case_host_leases(test_db, current, current["roster"][0])
    _complete_case(test_db, current)
    assert not execution_host_leases(test_db, current)
    assert all(
        test_db.execute(
            "SELECT released_at FROM work_claims WHERE id=%s", (claim.id,)
        ).fetchone()[0]
        for claim in leases
    )


def test_partial_acquisition_releases_first_host_and_queues_second(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True, driver=MACHINES[1])
    seed_qa_session(test_db, SESSION, "busy-host", messageable=True)
    held = acquire(test_db, make_qa_admission_target(MACHINES[1]), "busy-host")
    execution = _begin(test_db)
    response = _case_begin(execution)
    assert response.primary_success, response.error
    assert response.result_payload["state"] == "waiting"
    assert response.result_payload["host_wait"]["machine"] == MACHINES[1]
    assert not execution_host_leases(test_db, execution)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL AND target_kind='qa_admission'"
        ).fetchone()[0]
        == 1
    )
    release(test_db, held.id, "ready")
    resumed = _begin(test_db)
    assert resumed["id"] == execution["id"]
    response = _case_begin(resumed)
    assert response.primary_success, response.error
    leases = execution_host_leases(test_db, resumed)
    assert [claim.target.machine_id for claim in leases] == list(MACHINES)
    # Consuming one FIFO reservation must not cancel the companion host.
    assert all(claim.is_active for claim in leases)


def test_mission_review_retains_and_heartbeats_every_host(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    current = lock_plan_execution(test_db, execution["id"])
    leases = execution_host_leases(test_db, current)
    current["roster"][0]["runner_id"] = "agent_mission"
    case = current["roster"][0]
    advance_plan_execution(
        test_db,
        current,
        ordinal=0,
        requirement_id=case["requirement_id"],
        result={
            "requirement_id": case["requirement_id"],
            "case_outcome": "needs_review",
        },
    )
    finish_plan_execution(
        test_db, current, state="awaiting_agent_review", reason="review"
    )
    assert len(execution_host_leases(test_db, current)) == 2
    for claim in leases:
        test_db.execute(
            "UPDATE work_claims SET last_heartbeat='2020-01-01T00:00:00Z' WHERE id=%s",
            (claim.id,),
        )
    test_db.commit()
    heartbeat_plan_execution(test_db, current)
    assert all(
        test_db.execute(
            "SELECT last_heartbeat FROM work_claims WHERE id=%s", (claim.id,)
        ).fetchone()[0]
        != "2020-01-01T00:00:00Z"
        for claim in leases
    )
    finish_plan_execution(test_db, current, state="aborted", reason="review-aborted")
    assert not execution_host_leases(test_db, current)


def test_lost_companion_lease_refuses_before_case_continuation(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    leases = execution_host_leases(test_db, execution)
    release(test_db, leases[1].id, "forced-recovery")
    response = _case_begin(execution)
    assert not response.primary_success
    assert "test_machine_set_lease_lost" in response.error.message
    assert "abort" in response.error.message


def test_failed_finish_rolls_back_the_entire_host_set(test_db, tmp_path, monkeypatch):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    current = lock_plan_execution(test_db, execution["id"])
    lease_ids = [claim.id for claim in execution_host_leases(test_db, current)]
    with mock.patch(
        "yoke_core.domain.qa_plan_execution_lifecycle.dispose_execution_decisions",
        side_effect=ValueError("settlement failed"),
    ):
        with pytest.raises(ValueError, match="settlement failed"):
            finish_plan_execution(
                test_db, current, state="aborted", reason="rollback-check"
            )
    test_db.rollback()
    reloaded = lock_plan_execution(test_db, execution["id"])
    assert reloaded["state"] == "active"
    assert [claim.id for claim in execution_host_leases(test_db, reloaded)] == lease_ids


def test_failed_contract_issue_rolls_back_partial_acquisitions(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    with mock.patch(
        "yoke_core.domain.machine_qa_execution_protocol._issue",
        side_effect=ValueError("contract failed"),
    ):
        response = _case_begin(execution)
    assert not response.primary_success
    assert "contract failed" in response.error.message
    assert not execution_host_leases(test_db, execution)
    assert lock_plan_execution(test_db, execution["id"])["machine_lease_id"] is None


@pytest.mark.parametrize("parked,ended", [(False, True), (True, False)])
def test_stale_owner_cleanup_respects_parked_sessions_and_releases_full_set(
    test_db, tmp_path, monkeypatch, parked, ended
):
    from yoke_core.domain.qa_plan_execution_lifecycle import reap_stale_plan_executions

    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    test_db.execute(
        "UPDATE qa_plan_executions SET heartbeat_at='2020-01-01T00:00:00Z' WHERE id=%s",
        (execution["id"],),
    )
    test_db.execute(
        "UPDATE harness_sessions SET mode=%s,ended_at=%s WHERE session_id=%s",
        (
            "parked" if parked else "dash",
            "2020-01-01T00:00:00Z" if ended else None,
            SESSION,
        ),
    )
    test_db.commit()
    reaped = reap_stale_plan_executions(test_db)
    assert bool(reaped) is ended
    assert len(execution_host_leases(test_db, execution)) == (2 if parked else 0)


def test_concurrent_begin_reuses_one_complete_host_set(test_db, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from runtime.api.fixtures.pg_testdb import connect_test_database

    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: connect_test_database(str(test_db.info.dbname)),
    )
    barrier = Barrier(2)

    def begin():
        barrier.wait(timeout=10)
        return _case_begin(execution)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(begin) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert all(response.primary_success for response in responses), responses
    assert (
        responses[0].result_payload["execution"]["lease_id"]
        == responses[1].result_payload["execution"]["lease_id"]
    )
    assert len(execution_host_leases(test_db, execution)) == 2


@pytest.mark.parametrize(
    "config",
    [
        {"machines": list(MACHINES)},
        {"machine": MACHINES[0], "machines": [MACHINES[0], MACHINES[0]]},
        {"machine": "missing-driver", "machines": list(MACHINES)},
    ],
)
def test_invalid_host_sets_refuse_with_a_recovery(config):
    with pytest.raises(ValueError, match="test_machine_set_invalid"):
        normalize_config_machines(config)


def test_direct_execution_cannot_silently_drop_companion_hosts():
    from yoke_core.domain.machine_qa_execution_protocol import (
        begin_host_control_execution,
    )

    with pytest.raises(ValueError, match="test_machine_set_requires_plan"):
        begin_host_control_execution(
            None,
            project="yoke",
            session_id=SESSION,
            operation="case",
            cases=(
                {"method_config": {"machine": MACHINES[0], "machines": list(MACHINES)}},
            ),
        )


def test_mission_config_preserves_validated_simultaneous_hosts():
    from yoke_core.domain.qa_method_config_validation import validate_method_config

    config = validate_method_config(
        "agent-mission",
        {
            "executor": "informed_subagent",
            "machine": MACHINES[1],
            "machines": list(reversed(MACHINES)),
        },
    )
    assert config["machines"] == list(MACHINES)
    assert config["machine"] == MACHINES[1]


def test_scoped_cases_reach_a_shared_baseline_once():
    from yoke_core.domain.machine_qa_plan_protocol import plan_case_contract_arguments

    first = {
        "runner_id": "host_control",
        "plan_id": 1,
        "case_position": 1,
        "baseline_position": 1,
        "host_baseline": "fresh-host",
    }
    second = {**first, "case_position": 2}
    execution = {
        "id": "host-plan",
        "roster_digest": "frozen",
        "deployment_member_item_id": 42,
        "roster": [first, second],
    }
    assert plan_case_contract_arguments(execution, first, ordinal=0)["baselines"] == (
        "fresh-host",
    )
    assert plan_case_contract_arguments(execution, second, ordinal=1)["baselines"] == ()
    assert plan_case_contract_arguments(execution, {**second, "plan_id": 2}, ordinal=1)[
        "baselines"
    ] == ("fresh-host",)


def test_acquisition_order_does_not_depend_on_driving_host(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True, driver=MACHINES[1])
    from yoke_core.domain import machine_qa_host_selection

    acquire_host = machine_qa_host_selection.acquire_test_machine_admission
    with mock.patch.object(
        machine_qa_host_selection, "acquire_test_machine_admission", wraps=acquire_host
    ) as acquire_spy:
        response = _case_begin(_begin(test_db))
    assert response.primary_success, response.error
    assert [call.kwargs["machine"] for call in acquire_spy.call_args_list] == list(
        MACHINES
    )
