"""Project-default QA plan attachment per workflow transition."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_one
from yoke_core.domain.qa_plan_attachment_validation import require_plan_cases
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    _placeholder,
    _plan_row,
)


def set_project_default(
    conn: Any,
    *,
    plan_id: int,
    workflow_id: str,
    transition_id: str,
    qa_phase: str = "verification",
    actor_id: Optional[int] = None,
) -> dict:
    """Attach one of a transition's project-default plans."""
    plan = _plan_row(conn, plan_id)
    require_plan_cases(conn, plan_id)
    marker = _placeholder(conn)
    if (
        query_one(
            conn,
            f"SELECT 1 FROM workflows WHERE id={marker}",
            (workflow_id,),
        )
        is None
    ):
        raise QaPlanError(f"workflow {workflow_id!r} not found")
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_plan_project_defaults("
        "project_id, workflow_id, transition_id, qa_phase, plan_id, "
        "attached_at, attached_by_actor_id"
        f") VALUES ({', '.join([marker] * 7)}) "
        "ON CONFLICT(project_id, workflow_id, transition_id, plan_id) "
        "DO UPDATE SET qa_phase=EXCLUDED.qa_phase, "
        "attached_at=EXCLUDED.attached_at, "
        "attached_by_actor_id=EXCLUDED.attached_by_actor_id",
        (
            int(plan["project_id"]),
            workflow_id,
            transition_id,
            qa_phase,
            plan_id,
            now,
            actor_id,
        ),
    )
    conn.commit()
    return {
        "plan_id": int(plan_id),
        "project_id": int(plan["project_id"]),
        "workflow_id": workflow_id,
        "transition_id": transition_id,
        "qa_phase": qa_phase,
    }


def unset_project_default(
    conn: Any,
    *,
    plan_id: int,
    workflow_id: str,
    transition_id: str,
) -> dict:
    """Remove one transition's project-default plan attachment."""
    plan = _plan_row(conn, plan_id)
    marker = _placeholder(conn)
    where = (
        f"project_id={marker} AND workflow_id={marker} "
        f"AND transition_id={marker} AND plan_id={marker}"
    )
    params = (
        int(plan["project_id"]),
        workflow_id,
        transition_id,
        int(plan_id),
    )
    if (
        query_one(
            conn,
            f"SELECT 1 FROM qa_plan_project_defaults WHERE {where}",
            params,
        )
        is None
    ):
        raise QaPlanError(
            f"plan {plan_id} is not a project default for "
            f"workflow {workflow_id!r} transition {transition_id!r}"
        )
    conn.execute(
        f"DELETE FROM qa_plan_project_defaults WHERE {where}",
        params,
    )
    conn.commit()
    return {
        "plan_id": int(plan_id),
        "project_id": int(plan["project_id"]),
        "workflow_id": workflow_id,
        "transition_id": transition_id,
    }


__all__ = ["set_project_default", "unset_project_default"]
