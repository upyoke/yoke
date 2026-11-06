# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import _project

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_OWNER,
    ROLE_VIEWER,
    grant_actor_org_role,
    grant_actor_project_role,
)

from yoke_core.domain.deployment_qa_result_notice import (
    OUTCOME_PASSED,
    OUTCOME_REJECTED,
    notification_audience,
    notify_qa_stage_result,
    qa_result_idempotency_key,
)

OPERATOR = 9961


def _member(conn: Any, actor_id: int, *, role: str) -> None:
    conn.execute(
        "INSERT INTO actors(id,kind,name,created_at) VALUES "
        "(%s,'human',%s,'2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (actor_id, f"member-{actor_id}"),
    )
    grant_actor_project_role(conn, actor_id=actor_id, project_id=1, role_name=role)
    for row in conn.execute("SELECT org_id FROM projects WHERE id=1").fetchall():
        if row["org_id"] is not None:
            grant_actor_org_role(
                conn,
                actor_id=actor_id,
                org_id=int(row["org_id"]),
                role_name=ROLE_ADMIN,
            )
    conn.commit()
