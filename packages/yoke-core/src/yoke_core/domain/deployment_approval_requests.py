"""Decision-request adapter for a deployment run's human approval stage."""

from __future__ import annotations

from typing import Any, Mapping, Optional

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
        "SELECT dr.id, dr.project_id, dr.flow, dr.target_tier, "
        "e.name AS target_environment, dr.status, "
        "dr.current_stage, dr.created_by, p.slug AS project, df.stages "
        "FROM deployment_runs dr JOIN projects p ON p.id = dr.project_id "
        "JOIN deployment_flows df ON df.id = dr.flow "
        "LEFT JOIN environments e ON e.id = dr.target_environment_id "
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
    target = str(
        run["target_environment"]
        or run["target_tier"]
        or "the target environment"
    )
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
            "target_environment": run["target_environment"],
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


def emit_deployment_completion(
    conn: Any,
    *,
    run_id: str,
    event_name: str,
    outcome: str,
    context: Mapping[str, Any],
) -> str:
    """Append one terminal run event in the caller's transaction."""
    if event_name not in {"DeploymentRunSucceeded", "DeploymentRunFailed"}:
        raise ValueError(f"{event_name!r} is not a deployment completion event")
    run = _run(conn, run_id)
    from yoke_core.domain.events import emit_event

    event_context = dict(context)
    event_context["run_id"] = run_id
    event = emit_event(
        event_name,
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="system",
        severity="STATUS",
        outcome=outcome,
        project=str(run["project"]),
        context=event_context,
        conn=conn,
        transactional=True,
    )
    if not event.ok or not event.event_id:
        raise RuntimeError(
            f"could not append {event_name}: {event.reason or 'unknown error'}"
        )
    return event.event_id


def dispatch_deployment_stage_approval(
    run_id: str, stage_name: str,
) -> tuple[int, str]:
    """Deployment-step_runner adapter for one human approval stage."""
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


__all__ = [
    "deployment_stage_decision",
    "deployment_stage_is_approved",
    "dispatch_deployment_stage_approval",
    "ensure_deployment_stage_approval",
    "emit_deployment_completion",
]
