"""Shared fixture facts for shared-operation coordination-claim tests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.work_claim_targets import (
    make_migration_serialization_target,
    make_qa_admission_target,
    make_route_qualification_target,
)

PROJECT_YOKE = 1
PROJECT_OTHER = 2
MODEL = "primary"
MACHINE = "mac-mini-lab"
GRANT_KEY = "Z3JhbnQtdG9rZW4"


def seed_project(conn: Any, project_id: int, slug: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (project_id, slug, slug.title(), iso8601_now()),
    )
    conn.commit()


def seed_session(
    conn: Any,
    session_id: str,
    project_id: int = PROJECT_YOKE,
    *,
    ended: bool = False,
) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, ended_at) "
        "VALUES (%s, 'codex', 'openai', 'test-model', 'primary', %s, %s, "
        "'wait', %s, %s, 2, %s)",
        (
            session_id,
            f"/tmp/{session_id}",
            project_id,
            now,
            now,
            now if ended else None,
        ),
    )
    conn.commit()


def migration_target(item_id: int, project_id: int = PROJECT_YOKE, model: str = MODEL):
    return make_migration_serialization_target(project_id, model, item_id)


def qa_target(machine: str = MACHINE):
    return make_qa_admission_target(machine)


def qualification_target(project_id: int = PROJECT_YOKE, grant_key: str = GRANT_KEY):
    return make_route_qualification_target(project_id, grant_key)


__all__ = [
    "GRANT_KEY",
    "MACHINE",
    "MODEL",
    "PROJECT_OTHER",
    "PROJECT_YOKE",
    "migration_target",
    "qa_target",
    "qualification_target",
    "seed_project",
    "seed_session",
]
