# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_org_role, seed_project_role

from typing import Any

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    seed_roles_and_permissions,
)

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_qa_stage_wake import notify_item_scoped_qa_wait

from yoke_core.domain.work_claim_targets import make_item_target

HOLDER_A = "sess-holder-a"

HOLDER_B = "sess-holder-b"

SESSION_ACTOR_ID = 1


def _project(conn: Any) -> None:
    """The project, plus the send-message role every seeded session's
    actor needs to reach another session in it."""
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    seed_project_role(
        conn, actor_id=SESSION_ACTOR_ID, project_id=PROJECT_YOKE, role_name=ROLE_OWNER
    )
    row = conn.execute(
        "SELECT org_id FROM projects WHERE id=%s", (PROJECT_YOKE,)
    ).fetchone()
    seed_org_role(
        conn, actor_id=SESSION_ACTOR_ID, org_id=int(row[0]), role_name="viewer"
    )


def seed_session(conn: Any, session_id: str, project_id: int = PROJECT_YOKE) -> None:
    """A session whose route resolves ``messageable`` for real delivery.

    ``coordination_claim_test_support.seed_session`` leaves
    ``executor_surface``/``executor_version`` unset, which is fine for a
    deploy-lock claim's own identity but unmessageable — a Fleet send
    reads those columns for a real hook route, so this file's sessions
    need the shape :mod:`test_session_message_support` already proves is
    routable.
    """
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id,project_id,actor_id,workspace,"
        "executor,provider,executor_surface,executor_version,machine_id,"
        "execution_level,last_heartbeat,offered_at) VALUES "
        "(%s,%s,%s,'/tmp',%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            session_id,
            project_id,
            SESSION_ACTOR_ID,
            "claude-code",
            "anthropic",
            "claude-cli",
            "2.1.238",
            "m-wake-delivery-test",
            "direct",
            now,
            now,
        ),
    )
    conn.commit()


def _claim(conn: Any, *, session_id: str, target_kind: str, scope_json: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,"
        "last_heartbeat) VALUES (%s,%s,%s,%s,%s)",
        (session_id, target_kind, scope_json, now, now),
    )
    conn.commit()


def _recipients(conn: Any, idempotency_key: str) -> list[str]:
    rows = conn.execute(
        "SELECT r.session_id FROM session_messages m "
        "JOIN session_message_recipients r ON r.message_id = m.message_id "
        "WHERE m.idempotency_key = %s",
        (idempotency_key,),
    ).fetchall()
    return [row["session_id"] if hasattr(row, "keys") else row[0] for row in rows]


def _bodies(conn: Any, idempotency_key: str) -> list[str]:
    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key = %s",
        (idempotency_key,),
    ).fetchall()
    return [row["body"] if hasattr(row, "keys") else row[0] for row in rows]
