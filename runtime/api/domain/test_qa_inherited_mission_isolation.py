"""Deferred mission walks keep the state their predecessor prepared."""

import pytest

from runtime.api.domain.qa_member_machine_partitions_test_support import SESSION, _seed
from yoke_core.domain.qa_plan_chain_hosts import chain_host_groups
from yoke_core.domain.qa_plan_partition_chains import roster_partitions
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution
from yoke_core.domain.qa_standalone_partitions import standalone_partition_views


SLOTS = [{"os": "linux"}, {"os": "macos", "driver": True}]


def _roster():
    common = {
        "plan_id": 1, "baseline_position": 1, "execution_target_digest": "target",
        "verdict_path": "automatic",
    }
    return [
        {
            **common,
            "requirement_id": 1,
            "case_key": "prepare",
            "runner_id": "host_control",
            "method_config": {"test_machines": SLOTS},
        },
        {
            **common,
            "requirement_id": 2,
            "case_key": "walk",
            "starting_state": "inherit",
            "runner_id": "agent_mission",
            "method_config": {"test_machines": SLOTS},
        },
        {
            **common,
            "requirement_id": 3,
            "case_key": "independent",
            "runner_id": "host_control",
            "method_config": {"os": "macos"},
        },
    ]


def test_item_execution_isolates_a_mission_chain_on_the_same_target():
    roster = _roster()
    partitions = roster_partitions(roster)
    assert [[row["requirement_id"] for row in part.roster] for part in partitions] == [[1, 2], [3]]
    # Before admission a chain names no host: it carries its opener's slots.
    assert chain_host_groups(roster)[1] == ("macos", ("linux", "macos"), 1, None)
    assert chain_host_groups(roster)[3] == (None, (), None, "macos")


def test_mission_chain_does_not_cross_a_plan_or_baseline_boundary():
    roster = _roster()[:2]
    for boundary in ({"plan_id": 2}, {"baseline_position": 2}):
        separated = [roster[0], {**roster[1], **boundary}]
        assert chain_host_groups(separated)[1] == ("macos", ("linux", "macos"), None, None)


@pytest.mark.parametrize("trailing", [False, True])
def test_standalone_partition_keeps_the_inherited_mission_with_its_opener(
    test_db, tmp_path, monkeypatch, trailing
):
    _seed(test_db, tmp_path, monkeypatch, inherit=True, mission=True, trailing=trailing)
    test_db.execute(
        "UPDATE qa_plans SET target_environment_id=(SELECT id FROM environments "
        "WHERE project_id=1 AND name='stage') WHERE slug='host-check-0'"
    )
    test_db.commit()

    plan_id = test_db.execute(
        "SELECT id FROM qa_plans WHERE slug='host-check-0'"
    ).fetchone()[0]
    partitions = standalone_partition_views(test_db, plan_id, source_revision="a" * 40)

    def begin():
        return begin_standalone_execution(
            test_db,
            plan="host-check-0",
            project="yoke",
            actor_id="1",
            session_id=SESSION,
            source_revision="a" * 40,
            checkout_path=str(tmp_path),
            partition=partitions[0].partition.key,
        )

    execution = begin()
    assert len(execution["roster"]) == 2
    assert execution["roster"][-1]["starting_state"] == "inherit"
    if trailing:
        another = begin_standalone_execution(
            test_db, plan="host-check-0", project="yoke", actor_id="2",
            session_id="another-walker", source_revision="a" * 40,
            checkout_path=str(tmp_path),
            partition=partitions[1].partition.key,
        )
        assert len(another["roster"]) == 1
        assert another["id"] != execution["id"]


def test_each_chain_baseline_takes_only_its_own_chain_hosts(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import (
        TEST_MACHINE_SETTINGS,
        _terminal_recipe,
        verify_fixture_host,
    )
    from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
    from runtime.api.domain.qa_member_machine_partitions_test_support import (
        MACHINES,
        _case_begin,
        host_slots,
    )
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.domain.qa_plan_execution_state import (
        advance_plan_execution,
        finish_plan_execution,
        lock_plan_execution,
    )
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    _seed(test_db, tmp_path, monkeypatch)
    # An idle identical mac the chains never need to take.
    third = "mac-pro-lab"
    replace_test_machine_settings(
        test_db,
        power_project="yoke",
        test_machine=third,
        settings={**TEST_MACHINE_SETTINGS, "resource_name": third},
        base_settings=None,
    )
    verify_fixture_host(test_db, third)
    test_db.execute(
        "UPDATE qa_plans SET target_environment_id=(SELECT id FROM environments "
        "WHERE project_id=1 AND name='stage') WHERE slug='host-check-0'"
    )
    test_db.commit()
    plan_id = test_db.execute(
        "SELECT id FROM qa_plans WHERE slug='host-check-0'"
    ).fetchone()[0]
    replace_plan_cases(
        test_db,
        plan_id=plan_id,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "terminal-check",
                "instructions": "Run a host check.",
                "expected_outcome": "Check passes.",
                "method_config": {
                    **_terminal_recipe(),
                    **({"test_machines": host_slots()} if position > 1 else {"os": "macos"}),
                },
                "entry_surface": "printf done",
                "required_completion": "complete",
                "starting_state": "inherit" if position == 3 else "baseline",
                "host_baselines": [] if position == 3 else ["fresh-host"],
            }
            for position, key in enumerate(["independent", "opener", "follower"], 1)
        ],
    )
    partitions = standalone_partition_views(test_db, plan_id, source_revision="a" * 40)
    execution = begin_standalone_execution(
        test_db,
        plan="host-check-0",
        project="yoke",
        actor_id="1",
        session_id=SESSION,
        source_revision="a" * 40,
        checkout_path=str(tmp_path),
        partition=partitions[0].partition.key,
    )
    assert _case_begin(execution).primary_success
    current = lock_plan_execution(test_db, execution["id"])
    old_lease = current["test_machine_lease_id"]
    # The one-host chain holds exactly its driver.
    assert [lease.id for lease in execution_host_leases(test_db, current)] == [old_lease]
    opener = current["roster"][0]
    advance_plan_execution(
        test_db,
        current,
        ordinal=0,
        requirement_id=opener["requirement_id"],
        result={"requirement_id": opener["requirement_id"], "case_outcome": "passed"},
    )
    finish_plan_execution(test_db, current, state="completed", reason="first-partition")
    second = begin_standalone_execution(
        test_db, plan="host-check-0", project="yoke", actor_id="1", session_id=SESSION,
        source_revision="a" * 40, checkout_path=str(tmp_path),
        partition=partitions[1].partition.key,
    )
    assert second["id"] != execution["id"]
    response = _case_begin(second, 0)
    assert response.primary_success, response.error
    current = lock_plan_execution(test_db, second["id"])
    # The opener's baseline is not covered, so its slots are acquired anew; the
    # idle identical mac stays free.
    assert {
        lease.target.test_machine for lease in execution_host_leases(test_db, current)
    } == set(MACHINES)
    assert current["test_machine_lease_id"] != old_lease
    assert test_db.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (old_lease,)
    ).fetchone()[0]

    opener = current["roster"][0]
    advance_plan_execution(
        test_db,
        current,
        ordinal=0,
        requirement_id=opener["requirement_id"],
        result={"requirement_id": opener["requirement_id"], "case_outcome": "passed"},
    )
    response = _case_begin(current, 1)
    assert response.primary_success, response.error
    assert len(execution_host_leases(test_db, current)) == 2


def test_run_scoped_mission_chain_excludes_later_captures(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.qa_member_machine_partitions_test_support import (
        MACHINES,
        _begin,
        _case_begin,
    )
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    _seed(
        test_db,
        tmp_path,
        monkeypatch,
        inherit=True,
        mission=True,
        trailing=True,
        run_scope=True,
    )
    execution = _begin(test_db, deployment_member_item_id=None)
    assert [row["case_key"] for row in execution["roster"]] == list(MACHINES)
    assert execution["remaining_requirement_count"] == 1
    response = _case_begin(execution)
    assert response.primary_success, response.error
    assert len(execution_host_leases(test_db, execution)) == 2
