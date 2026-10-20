"""Deferred mission walks keep the state their predecessor prepared."""

from unittest.mock import patch

import pytest

from runtime.api.domain.test_qa_member_machine_partitions import SESSION, _seed
from yoke_core.domain.qa_plan_chain_hosts import chain_host_groups
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_plan_item_target_partition import item_target_partition
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution


def _roster():
    common = {"plan_id": 1, "baseline_position": 1, "execution_target_digest": "target"}
    return [
        {**common, "requirement_id": 1, "method_config": {"machine": "mac-lab"}},
        {
            **common,
            "requirement_id": 2,
            "starting_state": "inherit",
            "runner_id": "agent_mission",
            "method_config": {
                "machine": "mac-lab",
                "machines": ["linux-lab", "mac-lab"],
            },
        },
        {**common, "requirement_id": 3, "method_config": {"machine": "mac-lab"}},
    ]


def test_item_execution_isolates_a_mission_chain_on_the_same_target():
    roster = _roster()
    module = "yoke_core.domain.qa_plan_item_target_partition"
    with (
        patch(
            f"{module}.candidate_passed_requirements", return_value=("a" * 40, set())
        ),
        patch(f"{module}.live_plan_execution_id", return_value=None),
    ):
        _, selected, remaining = item_target_partition(
            None,
            roster,
            item_id=1,
            transition_id="reviewing-implementation",
            settle=lambda rows: (None, rows),
        )
    assert [row["requirement_id"] for row in selected] == [1, 2]
    assert remaining == 1
    assert chain_host_groups(roster)[1] == (
        "mac-lab",
        ("linux-lab", "mac-lab"),
        1,
    )


def test_host_union_does_not_cross_a_plan_or_baseline_boundary():
    roster = _roster()[:2]
    for boundary in ({"plan_id": 2}, {"baseline_position": 2}):
        separated = [roster[0], {**roster[1], **boundary}]
        assert chain_host_groups(separated)[1] == ("mac-lab", ("mac-lab",), None)


@pytest.mark.parametrize("trailing", [False, True])
def test_standalone_mission_chain_requires_its_own_plan(
    test_db, tmp_path, monkeypatch, trailing
):
    _seed(test_db, tmp_path, monkeypatch, inherit=True, mission=True, trailing=trailing)

    def begin():
        return begin_standalone_execution(
            test_db,
            plan="host-check-0",
            project="yoke",
            actor_id="1",
            session_id=SESSION,
            source_revision="a" * 40,
            checkout_path=str(tmp_path),
        )

    if trailing:
        with pytest.raises(
            QaPlanExecutionStateError, match="inherited_mission_requires_isolated_plan"
        ) as error:
            begin()
        assert "separate plan" in str(error.value)
    else:
        execution = begin()
        assert len(execution["roster"]) == 2
        assert execution["roster"][-1]["starting_state"] == "inherit"
