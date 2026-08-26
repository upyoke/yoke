"""Shared fixture facts for steering-scope claim behavior tests."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.steering_scope_claims import acquire

PROJECT_ALPHA = 71
PROJECT_BETA = 72
SESSION_ALPHA = "steering-alpha"
SESSION_BETA = "steering-beta"
SESSION_GAMMA = "steering-gamma"
STRATEGY_DOCS = ("MASTER-PLAN", "MISSION", "VISION")


def seed_project(conn: Any, project_id: int, slug: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) VALUES (%s, %s, %s, %s)",
        (project_id, slug, slug.title(), now),
    )
    for doc_slug in STRATEGY_DOCS:
        conn.execute(
            "INSERT INTO strategy_docs (project_id, slug, content, updated_at) "
            "VALUES (%s, %s, %s, %s)",
            (project_id, doc_slug, f"# {doc_slug}\n", now),
        )
    conn.commit()


def seed_session(conn: Any, session_id: str, project_id: int) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id) "
        "VALUES (%s, 'codex', 'openai', 'test-model', 'primary', %s, %s, "
        "'wait', %s, %s, 2)",
        (session_id, f"/tmp/{session_id}", project_id, now, now),
    )
    conn.commit()


def acquire_scope(
    conn: Any,
    session_id: str,
    project_id: int,
    doc_slugs: Sequence[str] = (),
):
    return acquire(
        conn,
        session_id=session_id,
        project_id=project_id,
        strategy_doc_slugs=doc_slugs,
        registered_by_actor_id=2,
        registered_by_session_id=session_id,
        reason="steering work",
    )


def seed_standard_scope_world(conn: Any) -> None:
    seed_project(conn, PROJECT_ALPHA, "alpha")
    seed_project(conn, PROJECT_BETA, "beta")
    seed_session(conn, SESSION_ALPHA, PROJECT_ALPHA)
    seed_session(conn, SESSION_BETA, PROJECT_ALPHA)
    seed_session(conn, SESSION_GAMMA, PROJECT_BETA)


__all__ = [
    "PROJECT_ALPHA",
    "PROJECT_BETA",
    "SESSION_ALPHA",
    "SESSION_BETA",
    "SESSION_GAMMA",
    "STRATEGY_DOCS",
    "acquire_scope",
    "seed_project",
    "seed_session",
    "seed_standard_scope_world",
]
