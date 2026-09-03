"""Focused SQLite fixtures for the session-message domain."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    grant_actor_org_role,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.session_control_schema import create_session_control_tables


NOW = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-08-22T16:00:00Z"
IDLE_WAKE_SESSION_ID = "s3"
NATIVE_WAKE_SESSION_ID = "s4"


def add_coordination_claim_schema(conn: sqlite3.Connection) -> None:
    """Add the exclusivity index a route-qualification grant relies on.

    ``message_connection`` already creates ``work_claims``; the grant only
    needs its kind's live-row uniqueness on top.
    """
    conn.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            idx_work_claims_active_route_qualification
            ON work_claims(scope)
            WHERE released_at IS NULL AND target_kind='route_qualification';
        """
    )


def message_connection(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE organizations (
            id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL,
            slug TEXT NOT NULL, name TEXT NOT NULL,
            public_item_prefix TEXT NOT NULL,
            default_branch TEXT NOT NULL DEFAULT 'main'
        );
        CREATE TABLE actors (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT 'human',
            system_component TEXT,
            created_at TEXT
        );
        CREATE TABLE actor_labels (
            id INTEGER PRIMARY KEY,
            actor_id INTEGER NOT NULL REFERENCES actors(id),
            surface TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(surface, label),
            UNIQUE(actor_id, surface)
        );
        CREATE TABLE roles (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            description TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE permissions (
            id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE,
            description TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE role_permissions (
            role_id INTEGER NOT NULL, permission_id INTEGER NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY (role_id, permission_id)
        );
        CREATE TABLE actor_project_roles (
            actor_id INTEGER NOT NULL, project_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL, granted_at TEXT NOT NULL,
            granted_by_actor_id INTEGER,
            PRIMARY KEY (actor_id, project_id, role_id)
        );
        CREATE TABLE actor_org_roles (
            actor_id INTEGER NOT NULL, org_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL, granted_at TEXT NOT NULL,
            granted_by_actor_id INTEGER,
            PRIMARY KEY (actor_id, org_id, role_id)
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
            project_sequence INTEGER NOT NULL
        );
        CREATE TABLE item_strategy_docs (
            item_id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
            strategy_doc_slug TEXT NOT NULL, linked_at TEXT NOT NULL
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
            lane_role TEXT, state TEXT, branch TEXT, path TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
            item_worktree_id INTEGER, PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY, project_id INTEGER NOT NULL,
            actor_id INTEGER,
            executor TEXT, executor_surface TEXT, executor_version TEXT,
            machine_id TEXT, execution_lane TEXT, last_heartbeat TEXT,
            last_tool_call_at TEXT, offered_at TEXT, ended_at TEXT,
            terminated_at TEXT, terminated_by_actor_id INTEGER,
            terminated_by_session_id TEXT, termination_reason TEXT,
            turn_posture TEXT NOT NULL DEFAULT 'unknown', turn_posture_at TEXT,
            model TEXT, reasoning_effort TEXT, context_window_tokens INTEGER,
            requested_model TEXT, requested_reasoning_effort TEXT,
            requested_context_window_tokens INTEGER,
            native_thread_id TEXT, offer_envelope TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
            target_kind TEXT NOT NULL, scope TEXT NOT NULL,
            claim_type TEXT NOT NULL DEFAULT 'exclusive',
            claimed_at TEXT NOT NULL,
            last_heartbeat TEXT, released_at TEXT, release_reason TEXT,
            reason TEXT, reason_intent TEXT, release_reason_intent TEXT
        );
        """
    )
    conn.executescript(
        f"""
        INSERT INTO organizations (id,slug,name) VALUES (1,'org','Org');
        INSERT INTO projects (id,org_id,slug,name,public_item_prefix) VALUES
            (1,1,'alpha','Alpha','ALP'), (2,1,'beta','Beta','BET');
        INSERT INTO actors (id) VALUES (10),(11),(12),(13);
        INSERT INTO actor_labels (actor_id,surface,label,created_at) VALUES
            (10,'display','Ada','2026-08-22T12:00:00Z'),
            (11,'display','Grace','2026-08-22T12:00:00Z');
        INSERT INTO items (id,project_id,project_sequence) VALUES
            (101,1,1),(201,2,1);
        INSERT INTO item_worktrees (id,item_id,lane_role,state,branch,path) VALUES
            (1,101,'integration','active','alpha-integration','/work/alpha-integration'),
            (2,101,'worker','active','alpha-worker','/work/alpha-worker');
        INSERT INTO epic_tasks (epic_id,task_num,item_worktree_id) VALUES (101,1,2);
        INSERT INTO harness_sessions (
            session_id,project_id,actor_id,executor,executor_surface,
            executor_version,
            machine_id,execution_lane,last_heartbeat,last_tool_call_at,offered_at,
            native_thread_id
        ) VALUES
            ('s1',1,10,'codex','codex-desktop','26.814.41407','m1','direct',
             '{NOW_TEXT}','{NOW_TEXT}','{NOW_TEXT}','codex-thread-s1'),
            ('s2',1,10,'claude-code','claude-cli','2.1.238','m2','worktree',
             '{NOW_TEXT}','{NOW_TEXT}','{NOW_TEXT}',NULL),
            ('{IDLE_WAKE_SESSION_ID}',2,10,'cursor','cursor-cli','2026.08.11','m3',
             'direct',
             '{NOW_TEXT}','{NOW_TEXT}','{NOW_TEXT}',NULL),
            ('{NATIVE_WAKE_SESSION_ID}',1,10,'codex','codex-cli',
             '0.148.0a15','m4','direct',
             '{NOW_TEXT}','{NOW_TEXT}','{NOW_TEXT}',NULL);
        INSERT INTO work_claims (
            id,session_id,target_kind,scope,claimed_at
        ) VALUES
            (1,'s1','item','{{"item_id":101}}','{NOW_TEXT}'),
            (2,'s2','epic_task','{{"epic_id":101,"task_num":1}}','{NOW_TEXT}'),
            (3,'s3','process','{{"conflict_group":"build-beta","process_key":"build-beta"}}','{NOW_TEXT}');
        """
    )
    create_session_control_tables(conn)
    seed_roles_and_permissions(conn)
    for project_id in (1, 2):
        grant_actor_project_role(
            conn, actor_id=10, project_id=project_id, role_name=ROLE_OPERATOR
        )
        grant_actor_project_role(
            conn, actor_id=11, project_id=project_id, role_name=ROLE_VIEWER
        )
    grant_actor_org_role(conn, actor_id=12, org_id=1, role_name=ROLE_ADMIN)
    conn.commit()
    return conn


def selector(**values: object) -> RecipientSelector:
    return RecipientSelector.model_validate(values)


__all__ = [
    "IDLE_WAKE_SESSION_ID",
    "NOW",
    "NOW_TEXT",
    "NATIVE_WAKE_SESSION_ID",
    "add_coordination_claim_schema",
    "message_connection",
    "selector",
]
