import pytest

from yoke_core.domain.qa_plan_partition_chains import roster_partitions
from yoke_core.domain.qa_plan_partition_custody import PartitionScope, PartitionUnavailable
from yoke_core.domain.qa_plan_partitions import partition_views, select_partition


def case(requirement, *, os=None, runner="host_control", state="baseline", target="a", after=None):
    return {
        "requirement_id": requirement,
        "plan_id": 1,
        "case_key": f"case-{requirement}",
        "baseline_position": 1,
        "starting_state": state,
        "runner_id": runner,
        "verdict_path": "automatic",
        "method_config": {"os": os} if os else {},
        "execution_target_digest": target,
        "after_case_key": after,
    }


def requirement_ids(partitions):
    return [[row["requirement_id"] for row in part.roster] for part in partitions]


def test_same_host_independent_chains_and_command_each_have_their_own_partition():
    roster = [
        case(1, os="windows"),
        case(2, state="inherit"),
        case(3, os="windows"),
        case(4, runner="ci_run", state=None),
    ]
    partitions = roster_partitions(roster, item_lane=True)
    assert requirement_ids(partitions) == [[1, 2], [3], [4]]
    assert [part.hosts for part in partitions] == [("windows",), ("windows",), ()]
    assert [part.kind for part in partitions] == ["walk", "walk", "lane"]
    assert all(not part.predecessors for part in partitions)


def test_only_an_explicit_predecessor_orders_independent_hosts():
    roster = [
        case(1, os="macos"),
        case(2, os="windows", after="case-1"),
        case(3, os="linux"),
    ]
    first, second, third = roster_partitions(roster)
    assert requirement_ids([first, second, third]) == [[1], [2], [3]]
    assert second.predecessors == (first.key,)
    assert not third.predecessors


def test_interleaved_target_rows_keep_their_own_inherited_chain():
    roster = [
        case(1, os="macos", target="a"),
        case(2, os="macos", target="b"),
        case(3, state="inherit", target="a"),
        case(4, state="inherit", target="b"),
    ]
    assert requirement_ids(roster_partitions(roster)) == [[1, 3], [2, 4]]


def test_keys_are_stable_and_standalone_ignores_materialized_requirement_ids():
    roster = [case(1, os="windows")]
    rematerialized = [{**roster[0], "requirement_id": 2}]
    assert roster_partitions(roster) == roster_partitions(roster)
    assert roster_partitions(roster)[0].key != roster_partitions(rematerialized)[0].key
    assert roster_partitions(roster, standalone=True)[0].key == (
        roster_partitions(rematerialized, standalone=True)[0].key
    )
    assert roster_partitions(roster)[0].key != roster_partitions(
        [{**roster[0], "execution_target_digest": "b"}]
    )[0].key


def test_partition_states_show_only_declared_order_and_exact_live_custody(monkeypatch):
    holder = {"id": "capture-1", "session_id": "walker-1"}
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_partitions.held_partition_cases",
        lambda conn, scope: {2: holder},
    )
    rows = [
        case(1, runner="ci_run", state=None),
        case(2, os="windows"),
        case(3, os="macos", after="case-1"),
        case(4, os="linux"),
        case(5, os="macos"),
        case(6, os="windows"),
    ]
    views = partition_views(
        None, PartitionScope(item_id=1, transition_id="release"),
        rows, passed={4}, failed={5},
    )
    assert [view.state for view in views] == [
        "lane", "held", "blocked", "passed", "failed", "free",
    ]
    assert views[2].as_dict()["blocked_by"] == [views[0].partition.key]
    assert views[1].as_dict()["execution_id"] == "capture-1"
    assert select_partition(views, key=views[1].partition.key, session_id="walker-1") == views[1]
    assert select_partition(views, key=views[5].partition.key, session_id="walker-2") == views[5]
    with pytest.raises(PartitionUnavailable, match="held by execution capture-1"):
        select_partition(views, key=views[1].partition.key, session_id="walker-2")
    with pytest.raises(PartitionUnavailable, match="waits for partitions"):
        select_partition(views, key=views[2].partition.key, session_id="walker-2")
