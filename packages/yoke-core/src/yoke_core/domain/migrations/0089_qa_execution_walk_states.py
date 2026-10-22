"""Separate mission walking from review after durable walk-end receipts.

The serving floor drains readers and writers of the retired state before
this atomic cutover. Boot applies it before admitting candidate traffic.
History owns the old spelling; current code never accepts or writes it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
_TABLE = "qa_plan_executions"
_OLD = "awaiting_agent_review"
_RETIRED = "'" + _OLD + "'::text"
_WAITING = "'waiting'::text"
_LIVE = "'active','waiting','walking','awaiting_walk_review'"
_STATES = _LIVE + ",'completed','aborted','error'"


def _decoded(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _walk_pending(conn: Any, execution_id: str, roster_json: Any) -> bool:
    for ordinal, case in enumerate(_decoded(roster_json)):
        if case.get("runner_id") != "agent_mission":
            continue
        result = conn.execute(
            "SELECT result_json FROM qa_plan_execution_results "
            "WHERE execution_id=%s AND ordinal=%s AND requirement_id=%s",
            (execution_id, ordinal, case["requirement_id"]),
        ).fetchone()
        run_id = _decoded(result[0]).get("run_id") if result else None
        restored = conn.execute(
            "SELECT 1 FROM qa_artifacts a JOIN qa_runs r ON r.id=a.qa_run_id "
            "WHERE a.qa_run_id=%s AND r.qa_requirement_id=%s "
            "AND a.artifact_type='starting_state_restore' LIMIT 1",
            (run_id, case["requirement_id"]),
        ).fetchone() if run_id else None
        if restored is None:
            return True
    return False


def apply(conn: Any) -> None:
    """Recode existing rows and every state-filtered uniqueness boundary."""
    if not _table_exists(conn, _TABLE):
        return
    conn.execute("LOCK TABLE qa_plan_executions IN ACCESS EXCLUSIVE MODE")
    constraints = conn.execute(
        "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='qa_plan_executions'::regclass AND contype='c'"
    ).fetchall()
    for name, expression in constraints:
        if re.search(r'\bstate\b', expression):
            conn.execute('ALTER TABLE qa_plan_executions DROP CONSTRAINT "'
                         + str(name).replace('"', '""') + '"')
    indexes = conn.execute(
        "SELECT indexname,indexdef FROM pg_indexes "
        "WHERE schemaname=current_schema() AND tablename=%s ORDER BY indexname",
        (_TABLE,),
    ).fetchall()
    for execution_id, roster in conn.execute(
        "SELECT id,roster_json FROM qa_plan_executions WHERE state=%s ORDER BY id",
        (_OLD,),
    ).fetchall():
        conn.execute(
            "UPDATE qa_plan_executions SET state=%s WHERE id=%s",
            ("walking" if _walk_pending(conn, str(execution_id), roster)
             else "awaiting_walk_review", execution_id),
        )
    conn.execute(
        "ALTER TABLE qa_plan_executions ADD CONSTRAINT "
        f"qa_plan_executions_state_check CHECK(state IN ({_STATES}))"
    )
    for name, definition in indexes:
        if _OLD not in definition:
            continue
        # pg_get_indexdef renders partial IN predicates as typed arrays. Each
        # state lands where the array's own order puts it: sorted arrays read
        # active,awaiting_walk_review,waiting,walking; the item-scoped index
        # keeps its schema order active,waiting,walking,awaiting_walk_review.
        if definition.count(_WAITING) != 1 or definition.count(_RETIRED) != 1:
            raise RuntimeError(
                "qa_state_index_shape_unknown: state index cannot be recoded; "
                "inspect its definition and correct this migration before retrying"
            )
        updated = definition.replace(
            _RETIRED, "'awaiting_walk_review'::text"
        ).replace(_WAITING, "'waiting'::text, 'walking'::text")
        conn.execute('DROP INDEX "' + str(name).replace('"', '""') + '"')
        conn.execute(updated)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, _TABLE):
        return
    if conn.execute(
        "SELECT 1 FROM qa_plan_executions WHERE state=%s LIMIT 1", (_OLD,)
    ).fetchone():
        raise RuntimeError(
            "qa_execution_state_not_converged: retired review states remain; "
            "rehearse and boot the walk-state migration before serving"
        )
    for (definition,) in conn.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname=current_schema() "
        "AND tablename=%s", (_TABLE,),
    ).fetchall():
        if re.search(r'\bstate\b', definition):
            assert _OLD not in definition and all(
                "'" + state + "'" in definition
                for state in ("active", "waiting", "walking", "awaiting_walk_review")
            ), "qa_execution_state_index_invalid: rehearse the walk-state migration"
    checks = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='qa_plan_executions'::regclass AND contype='c'"
    ).fetchall()
    assert any(
        "'walking'" in row[0] and "'awaiting_walk_review'" in row[0]
        and _OLD not in row[0] for row in checks
    ), "qa_execution_state_check_invalid: rehearse the walk-state migration"
