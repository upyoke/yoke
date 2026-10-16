"""QA table definitions and initialization."""

from __future__ import annotations

import sys

from typing import Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.qa_plan_execution_schema import (
    QA_PLAN_EXECUTION_SCHEMA_SQL,
)
from yoke_core.domain.qa_plan_review_schema import (
    QA_PLAN_REVIEW_SCHEMA_SQL,
)
from yoke_core.domain.qa_deployment_scope_schema import (
    REQUIREMENT_SUBJECT_CONSTRAINT,
)
from yoke_core.domain.qa_standalone_schema import (
    REQUIREMENT_SUBJECT_EXPRESSION,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


# ---------------------------------------------------------------------------
# QA schema
# ---------------------------------------------------------------------------

_QA_SCHEMA = (
    f"""
CREATE TABLE IF NOT EXISTS qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    standalone_execution_id TEXT,
    deployment_stage TEXT,
    deployment_member_item_id INTEGER,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL CHECK(qa_phase IN ('verification','post_deploy','manual_acceptance')),
    target_env TEXT,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking' CHECK(blocking_mode IN ('blocking','non_blocking')),
    requirement_source TEXT NOT NULL DEFAULT 'explicit' CHECK(requirement_source IN ('explicit','seeded_default','ac_derived','flow_derived')),
    success_policy TEXT,
    capability_requirements TEXT,
    suite_id TEXT,
    waived_at TIMESTAMPTZ,
    waiver_rationale TEXT,
    waiver_source TEXT,
    plan_id INTEGER,
    plan_case_key TEXT,
    case_position INTEGER,
    baseline_position INTEGER,
    method_id TEXT,
    method_name TEXT,
    runner_id TEXT,
    verdict_path TEXT,
    host_baseline TEXT,
    starting_state TEXT,
    starting_state_reason TEXT,
    entry_surface TEXT,
    required_completion TEXT,
    workflow_transition_id TEXT,
    instructions TEXT,
    expected_outcome TEXT,
    method_config TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT {REQUIREMENT_SUBJECT_CONSTRAINT}
        CHECK ({REQUIREMENT_SUBJECT_EXPRESSION})
);
CREATE INDEX IF NOT EXISTS idx_qa_requirements_item ON qa_requirements(item_id);
CREATE INDEX IF NOT EXISTS idx_qa_requirements_epic ON qa_requirements(epic_id, task_num);
CREATE INDEX IF NOT EXISTS idx_qa_requirements_deployment ON qa_requirements(deployment_run_id);

CREATE TABLE IF NOT EXISTS qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER NOT NULL,
    performed_by TEXT NOT NULL,
    qa_kind TEXT NOT NULL,
    verdict TEXT CHECK(verdict IN ('pass','fail','undetermined','error')),
    verdict_reason TEXT,
    execution_status TEXT CHECK(execution_status IN ('captured','capture_failed') OR execution_status IS NULL),
    case_outcome TEXT CHECK(case_outcome IN (
        'running','waiting','passed','failed','needs_review',
        'blocked_on_precondition'
    )),
    capture_degraded_reason TEXT,
    score REAL,
    confidence REAL,
    raw_result TEXT,
    duration_ms INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    CHECK(verdict <> 'undetermined' OR COALESCE(LENGTH(TRIM(verdict_reason)), 0) > 0),
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
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (qa_run_id) REFERENCES qa_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_qa_artifacts_run ON qa_artifacts(qa_run_id);
"""
    + QA_PLAN_EXECUTION_SCHEMA_SQL
    + QA_PLAN_REVIEW_SCHEMA_SQL
)


def cmd_init(*, db_path: Optional[str] = None) -> None:
    """Create QA tables (idempotent)."""
    from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger

    conn = connect(path=db_path)
    try:
        execute_schema_script(conn, _QA_SCHEMA)
        _ensure_qa_runs_verdict_trigger(conn)
        conn.commit()
    finally:
        conn.close()
    print("QA tables initialized", file=sys.stderr)
