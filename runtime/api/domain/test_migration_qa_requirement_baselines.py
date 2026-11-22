"""0117 gives open legacy ``as_is`` requirements a declared baseline.

Requirements materialized before ``as_is`` was removed could never begin
again. After the pass each open head starts from the baseline 0114's
derivation names, its inheriting followers share it, and retired rows and
run history keep what they recorded. A case that only named a Test Machine
runs on no host by today's meaning and gets no starting state; 0119 then
selects it by OS, and begin refuses it until a starting state is declared."""

import json
from pathlib import Path
import sqlite3

import pytest

from runtime.api.domain import migration_qa_hosts_by_os_test_support as hosts_by_os
from yoke_contracts.qa_case_starting_state import (
    STARTING_STATE_RECOVERY,
    StartingStateError,
    require_materialized_starting_state,
)
from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module

_COLUMNS = (
    "id", "item_id", "epic_id", "task_num", "deployment_run_id",
    "standalone_execution_id", "deployment_stage", "deployment_member_item_id",
    "workflow_transition_id", "qa_phase", "execution_target_digest", "plan_id",
    "baseline_position", "case_position", "plan_case_key", "runner_id",
    "capability_requirements", "method_config", "entry_surface",
    "starting_state", "starting_state_reason", "host_baseline",
    "retracted_at", "superseded_by_requirement_id", "waived_at",
)
_INTEGERS = {"id", "plan_id", "baseline_position", "case_position"}
_MACHINE = '{"test_machine":"windows-native-lab"}'


def _migration():
    path = Path(migrations.__file__).parent / "0117_declare_legacy_qa_requirement_baselines.py"
    return load_migration_module(path, path.stem)


def _connection(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TEMP TABLE qa_requirements("
        + ",".join(f"{name} {'INTEGER' if name in _INTEGERS else 'TEXT'}" for name in _COLUMNS)
        + ")"
    )
    conn.execute(
        "CREATE TEMP TABLE qa_plan_cases(id INTEGER, plan_id INTEGER, method_id TEXT, "
        "method_config TEXT, host_baselines TEXT, starting_state TEXT, updated_at TEXT)"
    )
    conn.execute("CREATE TEMP TABLE qa_runs(id INTEGER, historical_start TEXT)")
    conn.execute("INSERT INTO qa_runs VALUES (1,'as_is')")
    return conn


def _insert(conn, backend, **values):
    marker = "%s" if backend == "postgres" else "?"
    names = list(values)
    conn.execute(
        f"INSERT INTO qa_requirements({','.join(names)}) "
        f"VALUES ({','.join([marker] * len(names))})",
        tuple(values.values()),
    )


def _state(conn):
    return conn.execute(
        "SELECT id,starting_state,host_baseline,starting_state_reason "
        "FROM qa_requirements ORDER BY id"
    ).fetchall()


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_open_as_is_rows_converge_and_history_stays(test_db, backend):
    conn = _connection(test_db, backend)
    migration = _migration()
    mission = dict(runner_id="agent_mission", starting_state="as_is", starting_state_reason="old")
    # A planless item case, and its deployment-run copy that runs Yoke.
    _insert(conn, backend, id=1, item_id="5984", method_config=_MACHINE, **mission)
    _insert(
        conn, backend, id=2, deployment_run_id="run-030",
        plan_case_key="admitted-requirement-1",
        method_config='{"test_machine":"windows-native-lab","command":"yoke status"}',
        **mission,
    )
    # A planned chain: the follower's Yoke use decides the head's baseline.
    chain = dict(standalone_execution_id="exec-1", plan_id=7855, baseline_position=1)
    _insert(conn, backend, id=3, case_position=1, plan_case_key="welcome",
            runner_id="host_control", method_config="{}", starting_state="as_is", **chain)
    _insert(conn, backend, id=4, case_position=2, plan_case_key="apply",
            runner_id="host_control", method_config='{"command":"yoke status"}',
            starting_state="inherit", **chain)
    # Another execution's follower is not this chain's.
    _insert(conn, backend, id=5, case_position=2, plan_case_key="apply",
            runner_id="host_control", method_config="{}", starting_state="inherit",
            standalone_execution_id="exec-2", plan_id=7855, baseline_position=1)
    # A case on no Test Machine declares no starting state.
    _insert(conn, backend, id=6, item_id="4168", method_config="{}", **mission)
    # Retired rows keep their history.
    _insert(conn, backend, id=7, item_id="1", method_config=_MACHINE,
            retracted_at="2026-11-01", **mission)
    _insert(conn, backend, id=8, item_id="1", method_config=_MACHINE,
            superseded_by_requirement_id="9", **mission)
    _insert(conn, backend, id=9, item_id="1", method_config=_MACHINE,
            waived_at="2026-11-01", **mission)

    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)

    assert _state(conn) == [
        (1, None, None, None),
        (2, None, None, None),
        (3, "baseline", "shell-preconfigured", None),
        (4, "inherit", "shell-preconfigured", None),
        (5, "inherit", None, None),
        (6, None, None, None),
        (7, "as_is", None, "old"),
        (8, "as_is", None, "old"),
        (9, "as_is", None, "old"),
    ]
    assert conn.execute("SELECT historical_start FROM qa_runs").fetchone() == ("as_is",)

    hosts_by_os.add_tables(
        conn, backend, {"test_machines", "qa_methods", "qa_plans", "qa_plan_executions"}
    )
    hosts_by_os.register_host(conn, backend, "windows-native-lab", "windows")
    hosts_by_os.migration().apply(conn)

    configs = dict(conn.execute("SELECT id,method_config FROM qa_requirements").fetchall())
    assert json.loads(configs[1]) == {"os": "windows"}
    assert json.loads(configs[2]) == {"os": "windows", "command": "yoke status"}
    for row_id in (1, 2):
        with pytest.raises(StartingStateError, match="declares no valid starting state") as refused:
            require_materialized_starting_state(
                {"requirement_id": row_id, "starting_state": None, "host_baseline": None}
            )
        assert STARTING_STATE_RECOVERY in str(refused.value)


@pytest.mark.parametrize("table", ["qa_requirements", "qa_plan_cases"])
def test_invariant_fails_on_a_leftover_as_is_row(test_db, table):
    conn = _connection(test_db, "sqlite")
    migration = _migration()
    migration.apply(conn)
    conn.execute(f"INSERT INTO {table}(id,starting_state) VALUES (1,'as_is')")

    with pytest.raises(AssertionError, match=f"1 open {table} rows still use the removed as_is"):
        migration.invariants(conn)


def test_an_underivable_row_fails_the_migration_by_name(test_db):
    conn = _connection(test_db, "sqlite")
    _insert(conn, "sqlite", id=41, runner_id="agent_mission",
            method_config="{not json", starting_state="as_is")

    with pytest.raises(ValueError, match="QA requirement 41 has unreadable method_config"):
        _migration().apply(conn)
    assert _state(conn) == [(41, "as_is", None, None)]
