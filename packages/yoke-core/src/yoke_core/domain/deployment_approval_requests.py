"""Decision-request adapter for a deployment run's human approval stage."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run(conn: Any, run_id: str) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        "SELECT dr.id, dr.project_id, dr.flow, dr.target_env, dr.status, "
        "dr.current_stage, dr.created_by, p.slug AS project, df.stages "
        "FROM deployment_runs dr JOIN projects p ON p.id = dr.project_id "
        "JOIN deployment_flows df ON df.id = dr.flow "
        f"WHERE dr.id = {p}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} does not exist")
    return {key: row[key] for key in row.keys()}


def _existing_actor_id(conn: Any, value: Any) -> Optional[int]:
    text = str(value or "")
    if not text.isdigit():
        return None
    actor_id = int(text)
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {_p(conn)}", (actor_id,),
    ).fetchone()
    return actor_id if row is not None else None


def ensure_deployment_stage_approval(
    conn: Any,
    *,
    run_id: str,
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
) -> tuple[dict[str, Any], bool]:
    """Create or reuse the run stage's project owner/operator request."""
    run = _run(conn, run_id)
    if run["status"] != "executing" or not run["current_stage"]:
        raise ValueError(
            f"deployment run {run_id!r} is not waiting at an executing stage"
        )
    stage = str(run["current_stage"])
    from yoke_core.domain.approval import parse_flow_stages, resolve_approval

    resolution = resolve_approval(parse_flow_stages(str(run["stages"])), stage)
    if not resolution.approved:
        raise ValueError(resolution.error or "stage does not accept approval")
    target = str(run["target_env"] or "the target environment")
    originator = _existing_actor_id(
        conn,
        originator_actor_id
        if originator_actor_id is not None
        else run["created_by"],
    )
    history = list_subject_requests(
        conn, "deployment_stage", f"{run_id}:{stage}",
    )
    if history and history[0]["status"] == "resolved":
        return history[0], False
    return create_decision_request(
        conn,
        kind="deployment_stage_approval",
        subject_type="deployment_stage",
        subject_key=f"{run_id}:{stage}",
        project_id=int(run["project_id"]),
        originator_actor_id=originator,
        role_authorities=[
            RoleAuthority("project", int(run["project_id"]), "owner"),
            RoleAuthority("project", int(run["project_id"]), "operator"),
        ],
        subject_context={
            "run_id": run_id,
            "stage": stage,
            "target_env": run["target_env"],
            "flow_id": str(run["flow"]),
            "title": f"Deploy to {target} — approve the stage",
        },
        session_id=session_id,
    )


def deployment_stage_is_approved(
    conn: Any, *, run_id: str, stage_id: str,
) -> bool:
    """Return the retry/wait gate verdict for one exact run stage."""
    history = list_subject_requests(
        conn, "deployment_stage", f"{run_id}:{stage_id}",
    )
    return bool(
        history
        and history[0]["status"] == "resolved"
        and history[0]["resolution_action"] == "approve"
    )


def deployment_stage_decision(
    conn: Any, *, run_id: str, stage_id: str,
) -> Optional[str]:
    """Return the latest resolution action, or ``None`` while unresolved."""
    history = list_subject_requests(
        conn, "deployment_stage", f"{run_id}:{stage_id}",
    )
    if not history or history[0]["status"] != "resolved":
        return None
    action = history[0].get("resolution_action")
    return str(action) if action else None


def deployment_stage_approver_actor_ids(
    conn: Any, *, run_id: str,
) -> tuple[int, ...]:
    """Return the distinct actors who approved stages in one run."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT DISTINCT resolution_actor_id FROM decision_requests "
        "WHERE kind = 'deployment_stage_approval' "
        "AND subject_type = 'deployment_stage' "
        f"AND subject_key LIKE {p} AND status = 'resolved' "
        "AND resolution_action = 'approve' "
        "AND resolution_actor_id IS NOT NULL "
        "ORDER BY resolution_actor_id",
        (f"{run_id}:%",),
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def fan_out_deployment_completion(
    conn: Any,
    *,
    run_id: str,
    event_id: str,
    reason: str,
) -> int:
    """Address a terminal run event to its initiator and stage approvers."""
    from yoke_core.domain.decision_request_contract import (
        DEPLOYMENT_RUN_COMPLETED,
    )
    from yoke_core.domain.inbox_notifications import fan_out_registered_event

    p = _p(conn)
    run = conn.execute(
        f"SELECT created_by FROM deployment_runs WHERE id = {p}", (run_id,),
    ).fetchone()
    if run is None:
        raise LookupError(f"deployment run {run_id!r} does not exist")
    event = conn.execute(
        f"SELECT created_at FROM events WHERE event_id = {p}", (event_id,),
    ).fetchone()
    if event is None:
        return 0
    initiator = _existing_actor_id(conn, run[0])
    inserted = fan_out_registered_event(
        conn,
        event_id=event_id,
        notification_kind=DEPLOYMENT_RUN_COMPLETED,
        event_context={
            "initiator_actor_id": initiator,
            "stage_approver_actor_ids": deployment_stage_approver_actor_ids(
                conn, run_id=run_id,
            ),
        },
        reason=reason,
        created_at=str(event[0]),
    )
    conn.commit()
    return inserted


def dispatch_deployment_stage_approval(
    run_id: str, stage_name: str,
) -> tuple[int, str]:
    """Deployment-executor adapter for one human approval stage."""
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        request, _ = ensure_deployment_stage_approval(conn, run_id=run_id)
        decision = deployment_stage_decision(
            conn, run_id=run_id, stage_id=stage_name,
        )
    finally:
        conn.close()
    if decision == "approve":
        return 0, ""
    if decision == "reject":
        return 1, (
            f"deployment stage {stage_name!r} was rejected through "
            f"decision request {request['id']}"
        )
    print(
        f"Awaiting Inbox decision {request['id']} for stage '{stage_name}'"
    )
    return -2, ""


def notify_latest_deployment_completion(
    run_id: str, event_name: str, reason: str,
) -> int:
    """Address the just-emitted terminal run event, when one was persisted."""
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        p = _p(conn)
        rows = conn.execute(
            "SELECT event_id, envelope FROM events "
            f"WHERE event_name = {p} ORDER BY created_at DESC, id DESC LIMIT 50",
            (event_name,),
        ).fetchall()
        for row in rows:
            try:
                envelope = json.loads(row[1] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if str(envelope.get("context", {}).get("run_id") or "") != run_id:
                continue
            return fan_out_deployment_completion(
                conn, run_id=run_id, event_id=str(row[0]), reason=reason,
            )
        return 0
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


__all__ = [
    "deployment_stage_approver_actor_ids",
    "deployment_stage_decision",
    "deployment_stage_is_approved",
    "dispatch_deployment_stage_approval",
    "ensure_deployment_stage_approval",
    "fan_out_deployment_completion",
    "notify_latest_deployment_completion",
]
