"""SQL schema DDL for ``test_update_status_full*`` integration tests.

Mirrors the live tables ``runtime/api/domain/update_status`` reads or
writes through its subprocess entrypoint plus the ``epic_task_history``
view used by retry-cycle assertions. Kept in a dedicated module so the
``UpdateStatusEnv`` helper file can stay under the authored-file line
limit.
"""

from __future__ import annotations

from runtime.api.fixtures.schema_ddl_github_app import _GITHUB_APP_DDL
from yoke_core.domain.sql_json import json_get


_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS sprints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    activated_at TEXT,
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'issue',
    status TEXT NOT NULL DEFAULT 'idea',
    priority TEXT NOT NULL DEFAULT 'medium',
    flow TEXT DEFAULT 'accelerated',
    rework_count INTEGER DEFAULT 0,
    frozen INTEGER DEFAULT 0,
    sprint TEXT,
    track TEXT,
    track_seq INTEGER,
    github_issue TEXT,
    deployed_to TEXT,
    worktree TEXT,
    merged_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '2',
    project_id INTEGER NOT NULL DEFAULT 1,
    project_sequence INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS epic_tasks (
    id INTEGER PRIMARY KEY,
    epic_id INTEGER NOT NULL,
    task_num INTEGER NOT NULL,
    title TEXT,
    worktree TEXT,
    context_estimate TEXT,
    dependencies TEXT,
    status TEXT DEFAULT 'planned',
    dispatch_attempts INTEGER DEFAULT 0,
    body TEXT,
    github_issue TEXT,
    branch TEXT,
    worktree_path TEXT,
    blocked_by TEXT,
    max_attempts INTEGER DEFAULT 5,
    agent_id TEXT,
    last_heartbeat TEXT,
    UNIQUE(epic_id, task_num)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'system',
    session_id TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'INFO',
    event_kind TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    event_outcome TEXT,
    org_id TEXT,
    actor_id INTEGER,
    environment TEXT,
    service TEXT NOT NULL DEFAULT 'cli',
    project_id INTEGER DEFAULT 1,
    item_id TEXT,
    task_num INTEGER,
    sprint TEXT,
    agent TEXT,
    tool_name TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    trace_id TEXT,
    parent_id TEXT,
    anomaly_flags TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    hook_event_name TEXT,
    envelope TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_status_transitions (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    task_num INTEGER,
    from_status TEXT,
    to_status TEXT NOT NULL,
    source TEXT,
    session_id TEXT,
    actor_id INTEGER,
    project_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_activity_days (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    UNIQUE(project_id, item_id, day)
);
""" + f"""\
CREATE VIEW IF NOT EXISTS epic_task_history AS
SELECT id,
    CAST(REPLACE(item_id, 'YOK-', '') AS INTEGER) AS epic_id,
    task_num, created_at AS timestamp,
    COALESCE({json_get('envelope', '$.context.detail.from_status')},
             {json_get('envelope', '$.context.from_status')},
             {json_get('envelope', '$.from_status')}) AS from_status,
    COALESCE({json_get('envelope', '$.context.detail.to_status')},
             {json_get('envelope', '$.context.to_status')},
             {json_get('envelope', '$.to_status')}) AS to_status,
    COALESCE({json_get('envelope', '$.context.detail.note')},
             {json_get('envelope', '$.context.note')},
             {json_get('envelope', '$.note')}) AS note
FROM events WHERE event_type = 'task_status_change';
""" + """\
CREATE TABLE IF NOT EXISTS epic_task_files (
    id INTEGER PRIMARY KEY,
    epic_id INTEGER NOT NULL,
    task_num INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    action TEXT,
    FOREIGN KEY (epic_id, task_num) REFERENCES epic_tasks(epic_id, task_num)
);
CREATE TABLE IF NOT EXISTS harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    execution_lane TEXT NOT NULL DEFAULT 'primary',
    capabilities TEXT DEFAULT '[]',
    workspace TEXT NOT NULL,
    mode TEXT DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    offer_envelope TEXT,
    current_item_id TEXT DEFAULT NULL,
    current_item_set_at TEXT DEFAULT NULL,
    recent_item_id TEXT DEFAULT NULL,
    recent_item_status TEXT DEFAULT NULL,
    recent_item_recorded_at TEXT DEFAULT NULL,
    actor_id INTEGER DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    CHECK (
      (target_kind='item' AND item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='epic_task' AND item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND process_key IS NULL AND conflict_group IS NULL) OR
      (target_kind='process' AND item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND process_key IS NOT NULL AND conflict_group IS NOT NULL)
    ),
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    emoji TEXT DEFAULT '',
    default_branch TEXT DEFAULT 'main',
    github_repo TEXT,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
    created_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
);
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    config TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    settings TEXT DEFAULT '{}',
    UNIQUE(project_id, type)
);
CREATE TABLE IF NOT EXISTS capability_secrets (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'literal' CHECK(source = 'literal'),
    created_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    UNIQUE(project_id, type, key)
);
CREATE TABLE IF NOT EXISTS qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    check_name TEXT NOT NULL,
    qa_phase TEXT DEFAULT 'verification',
    success_policy TEXT DEFAULT 'blocking'
);
CREATE TABLE IF NOT EXISTS qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER NOT NULL,
    verdict TEXT
);
CREATE TABLE IF NOT EXISTS deployment_flows (
    id TEXT PRIMARY KEY,
    project_id INTEGER
);
""" + _GITHUB_APP_DDL

__all__ = ("_SCHEMA_DDL",)
