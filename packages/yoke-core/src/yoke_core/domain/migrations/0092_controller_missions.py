"""Remove inherited machine requirements from open controller-only missions."""

import json

from yoke_contracts.qa_case_starting_state import needs_test_machine
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def _changes(conn):
    """Preserve discharged requirements and snapshots owned by finished subjects."""
    if not _table_exists(conn, "qa_requirements"):
        return []
    rows = conn.execute(
        "SELECT q.id,q.method_config,q.capability_requirements,q.host_baseline,"
        "q.starting_state,q.starting_state_reason FROM qa_requirements q "
        "LEFT JOIN items i ON i.id=COALESCE(q.item_id,q.epic_id) "
        "LEFT JOIN qa_plan_executions e ON e.id=q.standalone_execution_id "
        "WHERE q.method_id='exploratory-mission' AND q.waived_at IS NULL "
        "AND q.superseded_by_requirement_id IS NULL AND q.retracted_at IS NULL "
        "AND q.replacement_requirement_id IS NULL "
        "AND NOT COALESCE(i.status IN ('done','cancelled'), FALSE) "
        "AND NOT COALESCE(e.state IN ('completed','aborted','error'), FALSE)"
    ).fetchall()
    changes = []
    for row_id, config, required, baseline, state, reason in rows:
        kinds = json.loads(required or "[]")
        if needs_test_machine(
            {
                "runner_id": "agent_mission",
                "method_config": config,
                "capability_requirements": kinds,
                "host_baseline": baseline,
            }
        ):
            continue
        kinds = [kind for kind in kinds if kind != "test-machine"]
        if (
            json.loads(required or "[]") != kinds
            or state is not None
            or reason is not None
        ):
            changes.append((json.dumps(kinds), row_id))
    return changes


def _plan_changes(conn):
    if not _table_exists(conn, "qa_plan_cases"):
        return []
    changes = []
    for row_id, config, baselines, state, reason in conn.execute(
        "SELECT id,method_config,host_baselines,starting_state,starting_state_reason "
        "FROM qa_plan_cases WHERE method_id='exploratory-mission'"
    ).fetchall():
        if not needs_test_machine(
            {
                "runner_id": "agent_mission",
                "method_config": config,
                "host_baselines": json.loads(baselines or "[]"),
            }
        ):
            if state is not None or reason is not None:
                changes.append(row_id)
    return changes


def apply(conn):
    marker = "%s" if connection_is_postgres(conn) else "?"
    for kinds, row_id in _changes(conn):
        conn.execute(
            f"UPDATE qa_requirements SET capability_requirements={marker},"
            f"starting_state=NULL,starting_state_reason=NULL WHERE id={marker}",
            (kinds, row_id),
        )
    for row_id in _plan_changes(conn):
        conn.execute(
            "UPDATE qa_plan_cases SET starting_state=NULL,starting_state_reason=NULL "
            f"WHERE id={marker}",
            (row_id,),
        )


def invariants(conn):
    assert not _changes(conn), "Open controller missions still require a Test Machine"
    assert not _plan_changes(conn), (
        "Controller plan cases still declare host starting state"
    )
