"""Simultaneous host acquisition retains both FIFO leases without deadlock."""

from unittest import mock

import pytest

from runtime.api.domain.qa_member_machine_partitions_test_support import (
    MACHINES,
    MEMBER,
    RUN,
    SESSION,
    _begin,
    _case_begin,
    _seed,
    host_slots,
    seed_fleet_cases,
)
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.deployment_qa_stage_execution_test_support import _complete_case
from yoke_core.domain.coordination_claims import release
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
    assert [claim.target.test_machine for claim in leases] == list(MACHINES)
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


def test_mission_review_retains_and_heartbeats_every_host(
    test_db, tmp_path, monkeypatch
):
    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    seed_qa_session(test_db, SESSION, messageable=True)
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
        test_db, current, state="awaiting_walk_review", reason="review"
    )
    recipient = test_db.execute(
        "SELECT session_id FROM session_message_recipients r JOIN session_messages m "
        "ON m.message_id=r.message_id WHERE m.idempotency_key=%s",
        (f"qa-plan-agent-review:{execution['id']}",),
    ).fetchone()[0]
    assert recipient == SESSION
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
        "yoke_core.domain.machine_qa_plan_protocol._issue",
        side_effect=ValueError("contract failed"),
    ):
        response = _case_begin(execution)
    assert not response.primary_success
    assert "contract failed" in response.error.message
    assert not execution_host_leases(test_db, execution)
    assert lock_plan_execution(test_db, execution["id"])["test_machine_lease_id"] is None


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


def test_removed_member_cleanup_releases_both_hosts_atomically(
    test_db, tmp_path, monkeypatch
):
    from yoke_core.domain.qa_deployment_member_removal import (
        abort_removed_member_executions,
    )

    _seed(test_db, tmp_path, monkeypatch, simultaneous=True)
    execution = _begin(test_db)
    assert _case_begin(execution).primary_success
    abort_removed_member_executions(test_db, run_id=RUN, item_ids=(MEMBER,))
    assert not execution_host_leases(test_db, execution)
    test_db.rollback()
    assert len(execution_host_leases(test_db, execution)) == 2
    assert lock_plan_execution(test_db, execution["id"])["state"] == "active"
    abort_removed_member_executions(test_db, run_id=RUN, item_ids=(MEMBER,))
    test_db.commit()
    assert not execution_host_leases(test_db, execution)
    assert lock_plan_execution(test_db, execution["id"])["state"] == "aborted"


@pytest.mark.parametrize(
    "config",
    [
        {"test_machines": [{"os": "linux"}, {"os": "macos"}]},
        {"test_machines": [{"os": "linux", "driver": True}, {"os": "macos", "driver": True}]},
        {"test_machines": [{"os": "macos", "driver": True}]},
        {"os": "macos", "test_machines": [{"os": "linux"}, {"os": "macos", "driver": True}]},
        {"test_machines": [{"os": "beos"}, {"os": "macos", "driver": True}]},
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
                {"method_config": {"test_machines": host_slots()}},
            ),
        )


def test_mission_config_preserves_validated_simultaneous_hosts():
    from yoke_core.domain.qa_method_config_validation import validate_method_config

    config = validate_method_config(
        "agent-mission",
        {
            "executor": "informed_subagent",
            "test_machines": [{"os": "linux"}, {"os": "macos", "driver": True}],
        },
    )
    assert config["test_machines"] == [{"os": "linux"}, {"os": "macos", "driver": True}]
    assert "test_machine" not in config


def test_each_chain_resets_and_an_inheriting_case_keeps_the_machine():
    from yoke_core.domain.machine_qa_plan_protocol import plan_case_contract_arguments

    first = {
        "runner_id": "host_control",
        "plan_id": 1,
        "case_position": 1,
        "baseline_position": 1,
        "host_baseline": "fresh-host",
        "starting_state": "baseline",
    }
    inheriting = {**first, "case_position": 2, "starting_state": "inherit"}
    fresh_again = {**first, "case_position": 3}

    def arguments(roster, ordinal):
        execution = {"id": "host-plan", "roster_digest": "frozen", "roster": roster}
        execution["deployment_member_item_id"] = 42
        return plan_case_contract_arguments(execution, roster[ordinal], ordinal=ordinal)

    chained = [first, inheriting]
    assert arguments(chained, 0)["baselines"] == ("fresh-host",)
    assert arguments(chained, 0)["cases"][0]["ends_chain"] is False
    assert arguments(chained, 1)["baselines"] == ()
    assert arguments(chained, 1)["cases"][0]["ends_chain"] is True
    # A later same-baseline case in the same member run opens its own chain.
    separate = [first, fresh_again]
    assert arguments(separate, 0)["cases"][0]["ends_chain"] is True
    assert arguments(separate, 1)["baselines"] == ("fresh-host",)


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
    assert [call.kwargs["test_machine"] for call in acquire_spy.call_args_list] == list(
        MACHINES
    )


def test_mac_only_tags_pass_the_windows_driver_and_pick_the_tagged_mac(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import TEST_MACHINE_SETTINGS as BASE, verify_fixture_host
    from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
    from yoke_core.domain.machine_qa_case_platform import require_host_tags

    slots = [{"os": "macos"}, {"os": "windows", "driver": True}]
    hosts = {"test_machines": slots, "capability_tags": {"macos": ["macos:15"]}}
    seed_fleet_cases(test_db, tmp_path, monkeypatch, {"win-a": "windows"}, [{"case_key": "mixed", "hosts": hosts}])
    tagged = {**BASE, "resource_name": "z-mac", "capability_tags": "macos:15"}
    replace_test_machine_settings(
        test_db, power_project="yoke", test_machine="z-mac", settings=tagged, base_settings=None,
    )
    verify_fixture_host(test_db, "z-mac")
    execution = _begin(test_db)
    response = _case_begin(execution)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, execution["id"])
    assert {c.target.test_machine for c in execution_host_leases(test_db, current)} == {"win-a", "z-mac"}
    require_host_tags({**BASE, "resource_name": "win-a", "os": "windows"}, current["roster"])
