"""Key open deployment cases by subject, independently of receipt provenance.

Drain older serving builds before applying with a named restore point: their
additive boot can recreate digest-keyed indexes. Duplicate evidence stays in
place; only the losing obligations are superseded.
"""

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.qa_deployment_scope_schema import (
    _REQUIREMENT_INDEX_SPECS,
    _assert_indexes,
    _index_sql,
)
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
_OBSOLETE_INDEXES = (
    "idx_qa_requirement_deployment_stage_materialization",
    "idx_qa_requirement_deployment_member_stage_materialization",
)


def apply(conn):
    if not _table_exists(conn, "qa_requirements"):
        return
    conn.execute(
        "WITH ranked AS (SELECT q.id,first_value(q.id) OVER ("
        "PARTITION BY q.deployment_run_id,q.deployment_stage,"
        "COALESCE(q.deployment_member_item_id,0),q.plan_id,q.plan_case_key,"
        "COALESCE(q.host_baseline,'') ORDER BY EXISTS ("
        "SELECT 1 FROM qa_runs r WHERE r.qa_requirement_id=q.id "
        "AND r.verdict='pass' AND r.completed_at IS NOT NULL "
        "AND COALESCE(r.case_outcome,'') NOT IN ('running','waiting')) DESC,q.id"
        ") AS survivor FROM qa_requirements q "
        "WHERE q.deployment_run_id IS NOT NULL AND q.deployment_stage IS NOT NULL "
        "AND q.plan_id IS NOT NULL AND q.superseded_by_requirement_id IS NULL "
        "AND q.retracted_at IS NULL) "
        "UPDATE qa_requirements q SET superseded_by_requirement_id=ranked.survivor,"
        "superseded_at=now(),supersession_source='migration',"
        "supersession_rationale='Converged duplicate deployment case identity' "
        "FROM ranked WHERE q.id=ranked.id AND ranked.id<>ranked.survivor"
    )
    for statement in _index_sql("qa_requirements", _REQUIREMENT_INDEX_SPECS).split(";"):
        if statement.strip():
            conn.execute(statement)
    for name in _OBSOLETE_INDEXES:
        conn.execute(f'DROP INDEX IF EXISTS "{name}"')


def invariants(conn):
    if not _table_exists(conn, "qa_requirements"):
        return
    _assert_indexes(conn, "qa_requirements", _REQUIREMENT_INDEX_SPECS)
    for name in _OBSOLETE_INDEXES:
        if conn.execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is not None:
            raise AssertionError(f"obsolete requirement index {name} remains")
