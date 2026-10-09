"""Schema and seed rows for API item fixture builders."""

from runtime.api.fixtures.schema_ddl_project_environments import (
    _PROJECT_ENVIRONMENT_TABLE_DDL,
)
from runtime.api.test_dependency_schema import ITEMS_SCHEMA, PROJECTS_SCHEMA
from yoke_core.domain.work_claim_target_sql import TARGET_KIND_CHECK_SQL

# Shared schema: ITEMS_SCHEMA (imported) + the family tables the API tests need.
# item_sections backs the section / progress-log writes; harness_sessions backs
# the dispatcher's actor-identity binding (queried on every mutating call).
_SCHEMA_DDL = (
    PROJECTS_SCHEMA
    + ITEMS_SCHEMA
    + _PROJECT_ENVIRONMENT_TABLE_DDL
    + f"""
CREATE TABLE project_capabilities (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, type TEXT NOT NULL,
    settings TEXT DEFAULT '{{}}', verified_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(project_id, type)
);
CREATE TABLE strategy_docs (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
    slug TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
    updated_by_actor_id INTEGER, archived_at TEXT, UNIQUE(project_id, slug)
);
CREATE TABLE strategy_doc_claims (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
    strategy_doc_slug TEXT NOT NULL, owner_kind TEXT NOT NULL DEFAULT 'item',
    owner_item_id INTEGER, owner_session_id TEXT,
    registered_by_actor_id INTEGER, registered_by_session_id TEXT,
    registered_at TEXT NOT NULL, released_by_actor_id INTEGER,
    released_by_session_id TEXT, released_at TEXT, release_mode TEXT,
    release_reason TEXT
);
CREATE TABLE deployment_flows (
    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,
    description TEXT, stages TEXT NOT NULL, on_failure TEXT DEFAULT 'halt',
    created_at TEXT NOT NULL, target_tier TEXT DEFAULT NULL,
    target_environment_id INTEGER DEFAULT NULL,
    done_description TEXT DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'active', UNIQUE(project_id, name)
);
CREATE TABLE deployment_runs (
    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, flow TEXT NOT NULL,
    target_tier TEXT, target_environment_id INTEGER, release_lineage TEXT,
    status TEXT NOT NULL DEFAULT 'created'
      CHECK(status IN ('created','executing','succeeded','failed','cancelled')),
    current_stage TEXT, created_at TEXT NOT NULL, started_at TEXT,
    completed_at TEXT, created_by TEXT DEFAULT 'operator'
);
CREATE TABLE deployment_run_items (
    run_id TEXT NOT NULL, item_id INTEGER NOT NULL, added_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
CREATE TABLE epic_tasks (
    epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL, title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', body TEXT, dependencies TEXT,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY, item_id INTEGER, epic_id INTEGER, task_num INTEGER,
    deployment_run_id TEXT, qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL DEFAULT 'verification', target_env TEXT,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT NOT NULL DEFAULT 'explicit',
    success_policy TEXT NOT NULL DEFAULT 'blocking', capability_requirements TEXT,
    suite_id TEXT, waived_at TEXT, waiver_rationale TEXT, created_at TEXT NOT NULL,
    plan_case_key TEXT, deployment_member_item_id INTEGER,
    superseded_by_requirement_id INTEGER
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY, qa_requirement_id INTEGER NOT NULL,
    performed_by TEXT, verdict TEXT, verdict_reason TEXT, execution_status TEXT,
    raw_result TEXT, case_outcome TEXT, completed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE item_sections (
    item_id INTEGER, section_name TEXT, content TEXT, ordering INTEGER,
    source TEXT DEFAULT 'operator', created_at TEXT, updated_at TEXT,
    PRIMARY KEY(item_id, section_name)
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY, actor_id INTEGER,
    project_id INTEGER NOT NULL DEFAULT 1,
    executor TEXT, executor_surface TEXT, provider TEXT, model TEXT,
    reasoning_effort TEXT DEFAULT NULL, context_window_tokens INTEGER DEFAULT NULL, requested_model TEXT DEFAULT NULL, requested_reasoning_effort TEXT DEFAULT NULL, requested_context_window_tokens INTEGER DEFAULT NULL,
    execution_level TEXT, executor_version TEXT, machine_id TEXT, workspace TEXT, mode TEXT,
    offered_at TEXT, last_heartbeat TEXT, ended_at TEXT,
    terminated_at TEXT, terminated_by_actor_id INTEGER,
    terminated_by_session_id TEXT, termination_reason TEXT,
    offer_envelope TEXT,
    current_item_id TEXT, current_item_set_at TEXT,
    recent_item_id TEXT, recent_item_status TEXT, recent_item_recorded_at TEXT,
    last_seen_main_sha TEXT, last_drift_check_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK({TARGET_KIND_CHECK_SQL}),
    scope TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT,
    reason TEXT DEFAULT NULL,
    reason_intent TEXT DEFAULT NULL,
    release_reason_intent TEXT DEFAULT NULL
);
"""
)


# (id, title, type, status, priority, project_slug, updated_at, deploy_stage,
#  deployment_flow). Item 4 sits at a human-approval stage in a flow with a run.
_SEED_ITEMS = (
    (
        1,
        "First item",
        "issue",
        "implementing",
        "high",
        "yoke",
        "2026-03-02T00:00:00Z",
        None,
        None,
    ),
    (
        2,
        "Second item",
        "epic",
        "done",
        "medium",
        "yoke",
        "2026-03-03T00:00:00Z",
        None,
        None,
    ),
    (
        3,
        "ExternalWebapp item",
        "issue",
        "idea",
        "low",
        "externalwebapp",
        "2026-03-04T00:00:00Z",
        None,
        None,
    ),
    (
        4,
        "Awaiting approval",
        "issue",
        "release",
        "high",
        "yoke",
        "2026-03-05T00:00:00Z",
        "approve-deploy",
        "test-approval-flow",
    ),
    (
        5,
        "Cancelled item",
        "issue",
        "cancelled",
        "low",
        "yoke",
        "2026-03-06T00:00:00Z",
        None,
        None,
    ),
)
