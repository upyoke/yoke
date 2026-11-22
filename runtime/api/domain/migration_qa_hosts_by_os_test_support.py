"""Temporary stored-QA tables and seeding for migration 0119's tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module

MIGRATION = "0119_select_qa_hosts_by_os"
HOSTS = {
    "lin-1": ("linux", "gpu"),
    "lin-2": ("linux", ""),
    "mac-1": ("macos", ""),
    "win-1": ("windows", ""),
    "win-2": ("windows", ""),
}
QUEUED_AT = "2026-11-01T08:00:00.000000Z"

_SCHEMA = (
    "CREATE TEMP TABLE test_machines(name TEXT, settings TEXT)",
    "CREATE TEMP TABLE qa_methods(id TEXT, runner_id TEXT)",
    "CREATE TEMP TABLE qa_plans(id INTEGER, retired_at TEXT)",
    "CREATE TEMP TABLE qa_plan_cases(id INTEGER, plan_id INTEGER, method_id TEXT, "
    "method_config TEXT, host_baselines TEXT, starting_state TEXT, updated_at TEXT)",
    "CREATE TEMP TABLE qa_requirements(id INTEGER, runner_id TEXT, method_config TEXT, "
    "capability_requirements TEXT, host_baseline TEXT, starting_state TEXT, retracted_at TEXT, "
    "superseded_by_requirement_id INTEGER, waived_at TEXT)",
    "CREATE TEMP TABLE qa_plan_executions(id TEXT, roster_json TEXT, roster_digest TEXT, "
    "cursor_ordinal INTEGER, session_id TEXT, state TEXT, release_reason TEXT, "
    "test_machine_lease_id INTEGER)",
    "CREATE TEMP TABLE qa_test_machine_waits(id TEXT, test_machine TEXT, session_id TEXT, "
    "actor_id INTEGER, queued_at TEXT, qa_plan_execution_id TEXT, state TEXT, "
    "claim_id INTEGER, resume_command TEXT, rationale TEXT, settled_at TEXT, need_id TEXT)",
    "CREATE UNIQUE INDEX temp_live_wait ON qa_test_machine_waits(test_machine, session_id) "
    "WHERE state IN ('waiting','reserved')",
    "CREATE TEMP TABLE qa_runs(id INTEGER, method_config TEXT)",
)


def migration():
    path = Path(migrations.__file__).parent / f"{MIGRATION}.py"
    return load_migration_module(path, path.stem)


def _table(statement):
    return statement.split("(")[0].split()[-1]


def add_tables(conn, backend, names):
    """Create the temporary tables 0119 reads that *names* lists."""
    for statement in _SCHEMA:
        if _table(statement) not in names:
            continue
        if backend == "postgres":
            statement = statement.replace("ON qa_test", "ON pg_temp.qa_test")
        conn.execute(statement)


def register_host(conn, backend, name, system):
    settings = json.dumps({"resource_name": name, "os": system})
    insert(conn, backend, "test_machines", name=name, settings=settings)


def connection(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    add_tables(conn, backend, {_table(statement) for statement in _SCHEMA})
    for name, (system, tags) in HOSTS.items():
        settings = {"resource_name": name, "os": system}
        if tags:
            settings["capability_tags"] = tags
        insert(conn, backend, "test_machines", name=name, settings=json.dumps(settings))
    for method, runner in (
        ("agent-mission", "agent_mission"),
        ("command", "worktree_run"),
        ("terminal-check", "host_control"),
    ):
        insert(conn, backend, "qa_methods", id=method, runner_id=runner)
    insert(conn, backend, "qa_plans", id=1, retired_at=None)
    insert(conn, backend, "qa_plans", id=2, retired_at="2026-10-01")
    insert(conn, backend, "qa_runs", id=1, method_config='{"test_machine":"win-1"}')
    return conn


def insert(conn, backend, table, **values):
    marker = "%s" if backend == "postgres" else "?"
    conn.execute(
        f"INSERT INTO {table}({','.join(values)}) "
        f"VALUES ({','.join([marker] * len(values))})",
        tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in values.values()),
    )


def rows(conn, sql):
    return [
        tuple(json.loads(v) if isinstance(v, str) and v[:1] in "[{" else v for v in row)
        for row in conn.execute(sql).fetchall()
    ]


def wait(conn, backend, wait_id, machine, execution_id, session, **values):
    insert(
        conn, backend, "qa_test_machine_waits", id=wait_id, test_machine=machine,
        session_id=session, actor_id=7, queued_at=QUEUED_AT,
        qa_plan_execution_id=execution_id, state=values.pop("state", "waiting"),
        resume_command=f"yoke qa plan run --resume-execution-id {execution_id}",
        rationale="host busy", need_id=values.pop("need_id", None), **values,
    )
