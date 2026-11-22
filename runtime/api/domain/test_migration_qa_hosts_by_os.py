"""0119 converts stored QA host names to OS selection, OS slots and any-of waits.

Open plan cases, requirements and live rosters that named a Test Machine
select by its OS afterwards; a name list becomes OS slots; a local Command's
inert ``os`` goes, so it stays local. Rows naming an unregistered host and
all history stay as stored, and a second run changes nothing.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone

import pytest

from runtime.api.domain.migration_qa_hosts_by_os_test_support import (
    connection,
    insert,
    migration,
    rows,
    wait,
    QUEUED_AT,
)
from yoke_contracts.qa_case_starting_state import (
    declares_starting_state,
    is_host_command,
)
from yoke_core.domain.machine_qa_case_machine import (
    MachineConstraintError,
    refuse_stored_host_names,
)
from yoke_core.domain.qa_plan_execution_store import roster_digest

_PINNED_MISSION = {
    "test_machine": "win-1", "test_machine_reason": "the lab host", "platform": "windows",
}
_SET_MISSION = {"test_machine": "mac-1", "test_machines": ["lin-1", "mac-1", "win-1"]}
_SLOTS = [{"os": "linux"}, {"os": "macos", "driver": True}, {"os": "windows"}]
_LOCAL = {"command": "true", "os": "linux", "platform": "linux"}
_PINNED_COMMAND = {"command": "true", "test_machine": "lin-2"}
_UNREGISTERED = {"command": "true", "test_machine": "gone-host"}


def test_migration_imports_only_its_frozen_dependencies():
    path = migration().__file__
    tree = ast.parse(open(path, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    assert imported == {
        "json",
        "hashlib",
        "yoke_contracts.timestamps.temporal_wire",
        "yoke_core.domain.db_backend.connection_is_postgres",
    }


def test_inlined_digest_equals_roster_digest():
    roster = [
        {"requirement_id": 3, "method_config": {"os": "linux", "z": [1, {"b": 2, "a": 1}]},
         "queued_at": datetime(2026, 11, 1, 8, tzinfo=timezone.utc), "note": "é"},
    ]
    assert migration()._digest(roster) == roster_digest(roster)


_BASELINE = {"host_baselines": ["fresh-host"], "starting_state": "baseline"}


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_open_cases_and_requirements_select_by_os(test_db, backend):
    conn = connection(test_db, backend)
    for case_id, method, config, plan, start in (
        (1, "agent-mission", _PINNED_MISSION, 1, {}),
        (2, "agent-mission", _SET_MISSION, 1, {}),
        (3, "command", _LOCAL, 1, {}),
        (4, "command", _PINNED_COMMAND, 1, _BASELINE),
        (5, "command", _UNREGISTERED, 1, _BASELINE),
        (6, "agent-mission", _PINNED_MISSION, 2, {}),
        (7, "command", _PINNED_COMMAND, 1, {}),
        (8, "command", _PINNED_COMMAND, 1, {"starting_state": "inherit"}),
    ):
        start = {"host_baselines": [], **start}
        insert(conn, backend, "qa_plan_cases", id=case_id, plan_id=plan,
               method_id=method, method_config=config, **start)
    kinds = ["browser", "test-machine:win-1"]
    based = {"host_baseline": "fresh-host", "starting_state": "baseline"}
    for row_id, runner, config, extra in (
        (11, "agent_mission", _PINNED_MISSION, {}),
        (12, "agent_mission", _SET_MISSION, {}),
        (13, "worktree_run", _LOCAL, {}),
        (14, "worktree_run", _PINNED_COMMAND, based),
        (15, "worktree_run", _UNREGISTERED, based),
        (16, "agent_mission", _PINNED_MISSION, {"retracted_at": "2026-11-01"}),
        (17, "agent_mission", _PINNED_MISSION, {"superseded_by_requirement_id": 11}),
        (18, "agent_mission", _PINNED_MISSION, {"waived_at": "2026-11-01"}),
        (19, "worktree_run", _PINNED_COMMAND, {}),
        (20, "worktree_run", _PINNED_COMMAND, dict(based, starting_state="inherit")),
    ):
        insert(conn, backend, "qa_requirements", id=row_id, runner_id=runner,
               method_config=config, capability_requirements=kinds, **extra)

    migration().apply(conn)
    once = rows(conn, "SELECT id,method_config,capability_requirements FROM qa_requirements ORDER BY id")
    migration().apply(conn)
    migration().invariants(conn)

    host_command = {"command": "true", "os": "linux"}
    assert rows(conn, "SELECT id,method_config FROM qa_plan_cases ORDER BY id") == [
        (1, {"os": "windows"}),
        (2, {"test_machines": _SLOTS}),
        (3, {"command": "true"}),
        (4, host_command),
        (5, _UNREGISTERED),
        (6, _PINNED_MISSION),
        (7, _PINNED_COMMAND),
        (8, host_command),
    ]
    requirements = rows(conn, "SELECT id,method_config,capability_requirements FROM qa_requirements ORDER BY id")
    assert requirements == once == [
        (11, {"os": "windows"}, ["browser"]),
        (12, {"test_machines": _SLOTS}, ["browser"]),
        (13, {"command": "true"}, ["browser"]),
        (14, host_command, ["browser"]),
        (15, _UNREGISTERED, kinds),
        (16, _PINNED_MISSION, kinds),
        (17, _PINNED_MISSION, kinds),
        (18, _PINNED_MISSION, kinds),
        (19, _PINNED_COMMAND, kinds),
        (20, host_command, ["browser"]),
    ]
    assert rows(conn, "SELECT method_config FROM qa_runs") == [({"test_machine": "win-1"},)]

    local = {"runner_id": "worktree_run", "method_config": requirements[2][1]}
    pinned = {"runner_id": "worktree_run", "method_config": requirements[3][1]}
    assert not declares_starting_state(local) and not is_host_command(local)
    assert declares_starting_state(pinned) and is_host_command(pinned)
    # Unregistered names and pinned Commands with no starting state stay, and
    # begin refuses them by name; neither runs locally.
    for row_id, config, _kinds in (requirements[4], requirements[8]):
        with pytest.raises(MachineConstraintError, match="test_machine_name_forbidden"):
            refuse_stored_host_names({"requirement_id": row_id, "method_config": config})


_BASED = {"host_baseline": "fresh-host", "starting_state": "baseline"}


def _entry(requirement_id, runner, config, kinds=()):
    return {
        "requirement_id": requirement_id, "runner_id": runner, "method_config": config,
        "required_capability_kinds": list(kinds), "host_baseline": None,
        "execution_target_digest": "target-1",
    }


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_live_rosters_convert_with_their_digest(test_db, backend):
    conn = connection(test_db, backend)
    roster = [
        _entry(21, "agent_mission", _PINNED_MISSION, ["test-machine:win-1"]),
        _entry(22, "worktree_run", _LOCAL),
        dict(_entry(23, "worktree_run", _PINNED_COMMAND, ["test-machine:lin-2"]), **_BASED),
        _entry(24, "worktree_run", _UNREGISTERED),
    ]
    admitted = "qa-communication-outcome-unknown:" + json.dumps({"case_admitted": 0})
    for execution_id, state, reason in (
        ("admitted", "waiting", admitted),
        ("unadmitted", "active", None),
        ("finished", "completed", None),
    ):
        insert(conn, backend, "qa_plan_executions", id=execution_id,
               roster_json=roster, roster_digest=roster_digest(roster), cursor_ordinal=0,
               session_id=f"session-{execution_id}", state=state, release_reason=reason,
               test_machine_lease_id=41)

    migration().apply(conn)
    migration().apply(conn)
    migration().invariants(conn)

    converted = [
        _entry(21, "agent_mission", {"os": "windows"}),
        _entry(22, "worktree_run", {"command": "true"}),
        dict(_entry(23, "worktree_run", {"command": "true", "os": "linux"}), **_BASED),
        _entry(24, "worktree_run", _UNREGISTERED),
    ]
    stored = rows(conn, "SELECT id,roster_json,roster_digest,test_machine_lease_id "
                        "FROM qa_plan_executions ORDER BY id")
    assert stored == [
        ("admitted", converted, roster_digest(converted), 41),
        ("finished", roster, roster_digest(roster), 41),
        ("unadmitted", converted, roster_digest(converted), 41),
    ]
    # A rewritten chain opener still needs a Test Machine.
    assert declares_starting_state(converted[2]) and is_host_command(converted[2])


def _waits(conn):
    return rows(conn, "SELECT qa_plan_execution_id,test_machine,state,need_id,queued_at,"
                      "session_id,rationale FROM qa_test_machine_waits "
                      "ORDER BY qa_plan_execution_id,test_machine")


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_live_waits_become_any_of_needs_at_their_place(test_db, backend):
    conn = connection(test_db, backend)
    tagged = dict(_PINNED_MISSION, test_machine="lin-2", capability_tags=["gpu"])
    for execution_id, config in (
        ("single", _PINNED_MISSION),
        ("set", _SET_MISSION),
        ("pair", {"test_machine": "lin-1", "test_machines": ["lin-1", "lin-2"]}),
        ("tagged", tagged),
        ("gone", _UNREGISTERED),
    ):
        roster = [_entry(31, "agent_mission", config)]
        insert(conn, backend, "qa_plan_executions", id=execution_id, roster_json=roster,
               roster_digest=roster_digest(roster), cursor_ordinal=0,
               session_id=f"s-{execution_id}", state="waiting")
    wait(conn, backend, "w-single", "win-1", "single", "s-single")
    for host in ("lin-1", "mac-1", "win-1"):
        wait(conn, backend, f"w-set-{host}", host, "set", "s-set")
    for host in ("lin-1", "lin-2"):
        wait(conn, backend, f"w-pair-{host}", host, "pair", "s-pair")
    wait(conn, backend, "w-tagged", "lin-2", "tagged", "s-tagged")
    wait(conn, backend, "w-gone", "gone-host", "gone", "s-gone")
    insert(conn, backend, "test_machines", name="lin-3",
           settings=json.dumps({"resource_name": "lin-3", "os": "linux"}))

    migration().apply(conn)
    after = _waits(conn)
    migration().apply(conn)
    migration().invariants(conn)
    assert _waits(conn) == after

    def need(execution_id, host):
        return next(row[3] for row in after if row[:2] == (execution_id, host))

    assert {row[4] for row in after if row[0] != "gone"} == {QUEUED_AT}
    assert all(row[6] == "host busy" for row in after)
    shape = [(row[0], row[1], row[2]) for row in after]
    assert shape == [
        ("gone", "gone-host", "waiting"),
        ("pair", "lin-1", "waiting"), ("pair", "lin-2", "waiting"),
        ("pair", "lin-3", "waiting"),
        ("set", "lin-1", "waiting"), ("set", "lin-2", "waiting"),
        ("set", "lin-3", "waiting"), ("set", "mac-1", "waiting"),
        ("set", "win-1", "waiting"), ("set", "win-2", "waiting"),
        ("single", "win-1", "waiting"), ("single", "win-2", "waiting"),
        ("tagged", "lin-1", "waiting"), ("tagged", "lin-2", "cancelled"),
    ]
    assert need("gone", "gone-host") is None
    assert need("single", "win-1") == need("single", "win-2") is not None
    # One need per slot: each OS's spare hosts join that OS's need.
    assert need("set", "lin-1") == need("set", "lin-2") == need("set", "lin-3")
    assert need("set", "win-1") == need("set", "win-2")
    assert len({need("set", host) for host in ("lin-1", "mac-1", "win-1")}) == 3
    # Two linux slots keep distinct needs and never share a host row.
    assert need("pair", "lin-1") != need("pair", "lin-2")
    assert need("pair", "lin-3") in {need("pair", "lin-1"), need("pair", "lin-2")}
    # A host without the case's tags leaves; a tagged host takes its place.
    assert need("tagged", "lin-1") == need("tagged", "lin-2")
