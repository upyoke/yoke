"""Shared fixture facts for project steering-claim behavior tests."""

from __future__ import annotations

from typing import Any

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.steering_claims import acquire
from yoke_core.domain.strategy_docs_create import create_doc

PROJECT_ALPHA = 71
PROJECT_BETA = 72
SESSION_ALPHA = "steering-alpha"
SESSION_BETA = "steering-beta"
SESSION_GAMMA = "steering-gamma"


def seed_project(conn: Any, project_id: int, slug: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) VALUES (%s, %s, %s, %s)",
        (project_id, slug, slug.title(), iso8601_now()),
    )
    conn.commit()
    seed_strategy_doc(conn, project_id, DEFAULT_STEERING_DOC_SLUG)


def seed_strategy_doc(conn: Any, project_id: int, slug: str) -> None:
    create_doc(conn, project_id, slug, f"# {slug}\n", actor_id=2)


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


def acquire_steering(
    conn: Any,
    session_id: str,
    project_id: int,
    *,
    doc_slug: str = DEFAULT_STEERING_DOC_SLUG,
):
    return acquire(
        conn,
        session_id=session_id,
        project_id=project_id,
        reason="steering work",
        doc_slug=doc_slug,
        actor_id=2,
    )


def seed_standard_steering_world(conn: Any) -> None:
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
    "acquire_steering",
    "seed_project",
    "seed_session",
    "seed_strategy_doc",
    "seed_standard_steering_world",
]
