"""QA schema DDL, init command, and QA-vocabulary migration.

Canonical owner of:

- ``_QA_SCHEMA`` — the QA tables/indexes DDL block.
- ``cmd_init`` — creates QA tables (idempotent) and runs the QA-vocab and
  execution-status migrations.
- ``_migrate_qa_vocab`` — rebuilds retired QA vocabulary in-place when an
  older schema is present.

``yoke_core.domain.schema`` imports ``_migrate_qa_vocab`` from this module
when wiring full schema initialization. The lazy import of
``_migrate_qa_execution_status`` inside :func:`cmd_init` avoids a circular
import between this module and ``yoke_core.domain.schema``.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.schema_common import (
    _get_check_constraint_defs,
    _table_exists,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


# ---------------------------------------------------------------------------
# QA schema
# ---------------------------------------------------------------------------

_QA_SCHEMA = """
CREATE TABLE IF NOT EXISTS qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL CHECK(qa_phase IN ('verification','post_deploy','manual_acceptance')),
    target_env TEXT,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking' CHECK(blocking_mode IN ('blocking','non_blocking')),
    requirement_source TEXT NOT NULL DEFAULT 'explicit' CHECK(requirement_source IN ('explicit','seeded_default','ac_derived','flow_derived')),
    success_policy TEXT,
    capability_requirements TEXT,
    suite_id TEXT,
    waived_at TEXT,
    waiver_rationale TEXT,
    waiver_source TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        (item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NULL) OR
        (item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND deployment_run_id IS NULL) OR
        (item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_qa_requirements_item ON qa_requirements(item_id);
CREATE INDEX IF NOT EXISTS idx_qa_requirements_epic ON qa_requirements(epic_id, task_num);
CREATE INDEX IF NOT EXISTS idx_qa_requirements_deployment ON qa_requirements(deployment_run_id);

CREATE TABLE IF NOT EXISTS qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER NOT NULL,
    executor_type TEXT NOT NULL,
    qa_kind TEXT NOT NULL,
    verdict TEXT CHECK(verdict IN ('pass','fail','inconclusive','error')),
    execution_status TEXT CHECK(execution_status IN ('captured','capture_failed') OR execution_status IS NULL),
    score REAL,
    confidence REAL,
    raw_result TEXT,
    duration_ms INTEGER,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (qa_requirement_id) REFERENCES qa_requirements(id)
);
CREATE INDEX IF NOT EXISTS idx_qa_runs_requirement ON qa_runs(qa_requirement_id);

CREATE TABLE IF NOT EXISTS qa_artifacts (
    id INTEGER PRIMARY KEY,
    qa_run_id INTEGER,
    artifact_type TEXT NOT NULL,
    content_type TEXT,
    artifact_handle TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (qa_run_id) REFERENCES qa_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_qa_artifacts_run ON qa_artifacts(qa_run_id);
"""

_QA_REQUIREMENTS_TABLE = "qa_requirements"
_QA_PHASE_CURRENT_VALUE = "verification"


# ---------------------------------------------------------------------------
# Init / migration
# ---------------------------------------------------------------------------

def cmd_init(*, db_path: Optional[str] = None) -> None:
    """Create QA tables (idempotent)."""
    # Lazy import avoids a circular import: ``schema`` imports
    # ``_migrate_qa_vocab`` from this module, and
    # ``schema_migrations`` is imported here only at call time.
    from yoke_core.domain.schema_migrations import _migrate_qa_execution_status

    conn = connect(path=db_path)
    try:
        execute_schema_script(conn, _QA_SCHEMA)
        _migrate_qa_vocab(conn)
        _migrate_qa_execution_status(conn)
        conn.commit()
    finally:
        conn.close()
    print("QA tables initialized")


def _qa_requirements_structurally_stale(conn) -> bool:
    """Detect stale QA vocabulary constraints through native schema probes."""
    constraint_defs = _get_check_constraint_defs(conn, _QA_REQUIREMENTS_TABLE)
    qa_phase_defs = [
        definition
        for definition in constraint_defs
        if "qa_phase" in definition
    ]
    if not qa_phase_defs:
        return False
    return not any(_QA_PHASE_CURRENT_VALUE in definition for definition in qa_phase_defs)


def _migrate_qa_vocab(conn) -> None:
    """Rebuild retired QA vocabulary in-place when an older schema is present."""
    if not _table_exists(conn, _QA_REQUIREMENTS_TABLE):
        return

    legacy_phase_count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_requirements WHERE qa_phase='validation'",
    ) or 0
    legacy_kind_count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_requirements WHERE qa_kind='review'",
    ) or 0
    legacy_run_kind_count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM qa_runs WHERE qa_kind='review'",
    ) or 0

    structural_stale = _qa_requirements_structurally_stale(conn)
    needs_rebuild = (
        structural_stale
        or legacy_phase_count > 0
        or legacy_kind_count > 0
        or legacy_run_kind_count > 0
    )
    if not needs_rebuild:
        return

    execute_schema_script(
        conn,
        """
        ALTER TABLE qa_requirements RENAME TO qa_requirements_old;

        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
            deployment_run_id TEXT,
            qa_kind TEXT NOT NULL,
            qa_phase TEXT NOT NULL CHECK(qa_phase IN ('verification','post_deploy','manual_acceptance')),
            target_env TEXT,
            blocking_mode TEXT NOT NULL DEFAULT 'blocking' CHECK(blocking_mode IN ('blocking','non_blocking')),
            requirement_source TEXT NOT NULL DEFAULT 'explicit' CHECK(requirement_source IN ('explicit','seeded_default','ac_derived','flow_derived')),
            success_policy TEXT,
            capability_requirements TEXT,
            suite_id TEXT,
            waived_at TEXT,
            waiver_rationale TEXT,
            waiver_source TEXT,
            created_at TEXT NOT NULL,
            CHECK (
                (item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NULL) OR
                (item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND deployment_run_id IS NULL) OR
                (item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NOT NULL)
            )
        );

        INSERT INTO qa_requirements (
            id, item_id, epic_id, task_num, deployment_run_id, qa_kind, qa_phase,
            target_env, blocking_mode, requirement_source, success_policy,
            capability_requirements, suite_id, waived_at, waiver_rationale,
            waiver_source, created_at
        )
        SELECT
            id,
            item_id,
            epic_id,
            task_num,
            deployment_run_id,
            CASE qa_kind WHEN 'review' THEN 'implementation_review' ELSE qa_kind END,
            CASE qa_phase WHEN 'validation' THEN 'verification' ELSE qa_phase END,
            target_env,
            blocking_mode,
            requirement_source,
            success_policy,
            capability_requirements,
            suite_id,
            waived_at,
            waiver_rationale,
            waiver_source,
            created_at
        FROM qa_requirements_old;

        DROP TABLE qa_requirements_old;

        UPDATE qa_runs
        SET qa_kind='implementation_review'
        WHERE qa_kind='review';
        """
    )
