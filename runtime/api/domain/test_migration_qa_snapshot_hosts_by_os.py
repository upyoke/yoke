"""0120 converts host pins in frozen deployment QA snapshots to OS form.

Run snapshot ``selections`` and ``plan_groups`` cases and member
``requirements`` convert exactly as 0119 converts their heads; a pin to an
unregistered host and an untouched null entry stay byte-for-byte; the
obsolete member ``plans`` copy is deleted; a second run changes nothing.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.migration_qa_hosts_by_os_test_support import (
    connection,
    insert,
    migration,
)

NAME = "0120_convert_snapshot_hosts_to_os"
_PINNED = {"test_machine": "win-1", "test_machine_reason": "the lab host"}
_SET = {"test_machine": "mac-1", "test_machines": ["lin-1", "mac-1"]}
_SLOTS = [{"os": "linux"}, {"os": "macos", "driver": True}]


def _case(key, config, kinds=None, **extra):
    case = {
        "case_key": key, "runner_id": "agent_mission", "method_id": "agent-mission",
        "method_config": config, "required_capability_kinds": kinds,
        "host_baselines": [], "starting_state": None,
    }
    return {**case, **extra}


def _requirement(row_id, config, kinds=None):
    return {
        "id": row_id, "runner_id": "agent_mission", "method_config": config,
        "capability_requirements": kinds, "host_baseline": None, "starting_state": None,
    }


def _seed(conn):
    run = {
        "schema": 1, "flow_id": "flow-a",
        "selections": [{"stage": "smoke", "cases": [
            _case("pinned", _PINNED, ["test-machine:win-1", "browser"]),
            _case("gone", {"test_machine": "gone-host"}),
        ]}],
        "plan_groups": {"19834": {"cases": [_case("set", _SET, [])]}},
    }
    insert(conn, "postgres", "deployment_runs", id="run-a", status="executing",
           requirement_snapshot=json.dumps(run))
    member = {
        "schema": 1, "selection": {"schema": 1, "plan_ids": [], "requirement_ids": [1, 2]},
        "requirements": [_requirement(1, {"test_machine": "lin-2"}), _requirement(2, None)],
        "plans": [{"plan": {"id": 9}, "cases": [_case("old", _PINNED)]}],
    }
    insert(conn, "postgres", "deployment_run_items", run_id="run-a", item_id=7,
           requirement_snapshot=json.dumps(member))
    insert(conn, "postgres", "deployment_runs", id="run-null", status="succeeded",
           requirement_snapshot=None)


def _snapshot(conn, sql):
    return json.loads(conn.execute(sql).fetchone()[0])


def _stored(conn):
    return [
        tuple(row)
        for table in ("deployment_runs", "deployment_run_items")
        for row in conn.execute(f"SELECT requirement_snapshot FROM {table} ORDER BY 1").fetchall()
    ]


def test_frozen_copies_select_by_os(test_db):
    conn = connection(test_db, "postgres")
    _seed(conn)
    migration(NAME).apply(conn)
    run = _snapshot(conn, "SELECT requirement_snapshot FROM deployment_runs WHERE id='run-a'")
    pinned, gone = run["selections"][0]["cases"]
    assert pinned["method_config"] == {"os": "windows"}
    assert pinned["required_capability_kinds"] == ["browser"]
    assert gone["method_config"] == {"test_machine": "gone-host"}
    assert run["plan_groups"]["19834"]["cases"][0]["method_config"] == {
        "test_machines": _SLOTS
    }
    member = _snapshot(conn, "SELECT requirement_snapshot FROM deployment_run_items")
    assert "plans" not in member
    converted, untouched = member["requirements"]
    assert converted["method_config"] == {"os": "linux"}
    assert converted["capability_requirements"] is None
    assert untouched["method_config"] is None
    assert conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id='run-null'"
    ).fetchone()[0] is None


def test_replay_is_a_no_op_and_invariants_hold(test_db):
    conn = connection(test_db, "postgres")
    _seed(conn)
    module = migration(NAME)
    module.apply(conn)
    before = _stored(conn)
    _, runs, items = module._pending(conn)
    assert (runs, items) == ([], [])
    module.apply(conn)
    module.invariants(conn)
    assert _stored(conn) == before


def test_an_untouched_snapshot_is_not_rewritten(test_db):
    conn = connection(test_db, "postgres")
    stored = '{"schema": 1, "selections": [{"cases": [{"method_config": null}]}]}'
    insert(conn, "postgres", "deployment_runs", id="run-b", status="succeeded",
           requirement_snapshot=stored)
    migration(NAME).apply(conn)
    assert conn.execute("SELECT requirement_snapshot FROM deployment_runs").fetchone()[0] == stored


@pytest.mark.parametrize(
    ("table", "values", "named"),
    [
        ("deployment_runs", {"id": "run-c", "status": "cancelled", "requirement_snapshot":
         json.dumps({"plan_groups": {"1": {"cases": [_case("p", _PINNED)]}}})}, "run-c"),
        ("deployment_run_items", {"run_id": "run-c", "item_id": 3, "requirement_snapshot":
         json.dumps({"requirements": [], "plans": []})}, "run-c/3"),
    ],
)
def test_invariants_name_a_row_still_holding_a_pin(test_db, table, values, named):
    conn = connection(test_db, "postgres")
    insert(conn, "postgres", table, **values)
    with pytest.raises(AssertionError, match=rf"{table} rows {named} still hold"):
        migration(NAME).invariants(conn)


def test_snapshot_case_digests_like_its_0119_converted_head(test_db):
    from yoke_core.domain.qa_deployment_case_content_refresh import (
        case_content_digest,
        plan_case_content_digest,
    )

    conn = connection(test_db, "postgres")
    config = {"command": "true", "test_machine": "lin-2"}
    case = _case("cmd", config, [], runner_id="worktree_run", method_id="command",
                 host_baselines=["fresh-host"], starting_state="baseline",
                 instructions="Run it.", expected_outcome="It passes.",
                 config_contract_id="command")
    insert(conn, "postgres", "qa_requirements", id=5, runner_id="worktree_run",
           method_config=config, capability_requirements=None,
           host_baseline="fresh-host", starting_state="baseline")
    insert(conn, "postgres", "deployment_runs", id="run-d", status="executing",
           requirement_snapshot=json.dumps({"selections": [{"cases": [case]}]}))
    migration("0119_select_qa_hosts_by_os").apply(conn)
    migration(NAME).apply(conn)
    head_config = json.loads(conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=5"
    ).fetchone()[0])
    frozen = _snapshot(conn, "SELECT requirement_snapshot FROM deployment_runs")
    frozen_case = frozen["selections"][0]["cases"][0]
    assert frozen_case["method_config"] == head_config == {"command": "true", "os": "linux"}
    head = {**frozen_case, "method_config": head_config}
    assert plan_case_content_digest(conn, frozen_case) == case_content_digest(head)
