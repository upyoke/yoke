"""Decision-request adapter for a deployment run's human approval stage."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_requests import (
    create_decision_request,
    list_subject_requests,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run(conn: Any, run_id: str, *, for_update: bool = False) -> dict[str, Any]:
    p = _p(conn)
    suffix = ""
    if for_update and db_backend.connection_is_postgres(conn):
        suffix = " FOR UPDATE OF dr"
    row = conn.execute(
        "SELECT dr.id, dr.project_id, dr.flow, dr.target_tier, "
        "e.name AS target_environment, dr.status, "
        "dr.current_stage, dr.created_by, p.slug AS project, p.org_id, "
        "df.stages "
        "FROM deployment_runs dr JOIN projects p ON p.id = dr.project_id "
        "JOIN deployment_flows df ON df.id = dr.flow "
        "LEFT JOIN environments e ON e.id = dr.target_environment_id "
        f"WHERE dr.id = {p}{suffix}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} does not exist")
    return {key: row[key] for key in row.keys()}


def _matches_deployment_snapshot(
    request: dict[str, Any],
    run: dict[str, Any],
    stage: str,
) -> bool:
    context = request.get("subject_context")
    if not isinstance(context, dict):
        return False
    return (
        str(context.get("run_id") or "") == str(run["id"])
        and str(context.get("stage") or "") == stage
        and str(context.get("flow_id") or "") == str(run["flow"])
        and str(context.get("target_environment") or "")
        == str(run["target_environment"] or "")
        and request.get("consumed_at") is None
    )


def _existing_actor_id(conn: Any, value: Any) -> Optional[int]:
    text = str(value or "")
    if not text.isdigit():
        return None
    actor_id = int(text)
    row = conn.execute(
        f"SELECT 1 FROM actors WHERE id = {_p(conn)}",
        (actor_id,),
    ).fetchone()
    return actor_id if row is not None else None


def evaluate_deployment_stage_approval(
    conn: Any,
    *,
    run_id: str,
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
):
    """Fail closed until an authorized approval resolves this run stage."""
    from yoke_core.domain.approval import parse_flow_stages, resolve_approval
    from yoke_core.domain.approval_gate import (
        ApprovalGateVerdict,
        role_authorities_for,
        verdict_from_request_history,
    )
    from yoke_core.domain.flow_validation import (
        MISSING_STAGE_APPROVALS,
        parse_stage_approvals,
    )

    run = _run(conn, run_id, for_update=True)
    if run["status"] != "executing" or not run["current_stage"]:
        raise ValueError(
            f"deployment run {run_id!r} is not waiting at an executing stage"
        )
    stage = str(run["current_stage"])
    stages = parse_flow_stages(str(run["stages"]))
    resolution = resolve_approval(stages, stage)
    if not resolution.approved:
        raise ValueError(resolution.error or "stage does not accept approval")
    stage_def = next(entry for entry in stages if entry.name == stage)
    if "approvals" not in stage_def.config:
        raise ValueError(MISSING_STAGE_APPROVALS.format(name=stage))
    roles, actors = parse_stage_approvals(
        stage_def.config.get("approvals"),
        path=f"stage {stage!r} approvals",
    )
    waiting = "the stage is waiting for a human decision"
    verdict = verdict_from_request_history(
        conn,
        list_subject_requests(conn, "deployment_stage", f"{run_id}:{stage}"),
        snapshot_matches=lambda request: _matches_deployment_snapshot(
            request,
            run,
            stage,
        ),
        session_id=session_id,
        stale_reason="deployment run flow or target changed",
        reraise_after_reject=False,
        waiting_reason=waiting,
        approved_reason="the declared approval was resolved",
        rejected_reason="the stage was rejected",
    )
    if verdict is not None:
        conn.commit()
        return verdict
    target = str(
        run["target_environment"] or run["target_tier"] or "the target environment"
    )
    originator = _existing_actor_id(
        conn,
        originator_actor_id if originator_actor_id is not None else run["created_by"],
    )
    request, _ = create_decision_request(
        conn,
        kind="deployment_stage_approval",
        subject_type="deployment_stage",
        subject_key=f"{run_id}:{stage}",
        project_id=int(run["project_id"]),
        originator_actor_id=originator,
        role_authorities=role_authorities_for(
            project_id=int(run["project_id"]),
            org_id=run["org_id"],
            role_names=roles,
        ),
        named_actor_ids=actors,
        subject_context={
            "run_id": run_id,
            "stage": stage,
            "target_environment": run["target_environment"],
            "flow_id": str(run["flow"]),
            "title": f"Deploy to {target} — approve the stage",
        },
        session_id=session_id,
    )
    return ApprovalGateVerdict(
        False,
        int(request["id"]),
        "pending",
        None,
        waiting,
    )


def deployment_stage_is_approved(
    conn: Any,
    *,
    run_id: str,
    stage_id: str,
) -> bool:
    """Return the retry/wait gate verdict for one exact run stage."""
    history = list_subject_requests(
        conn,
        "deployment_stage",
        f"{run_id}:{stage_id}",
    )
    return bool(
        history
        and history[0]["status"] == "resolved"
        and history[0]["resolution_action"] == "approve"
    )


def deployment_stage_decision(
    conn: Any,
    *,
    run_id: str,
    stage_id: str,
) -> Optional[str]:
    """Return the latest resolution action, or ``None`` while unresolved."""
    history = list_subject_requests(
        conn,
        "deployment_stage",
        f"{run_id}:{stage_id}",
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
    run_id: str,
    stage_name: str,
) -> tuple[int, str]:
    """Deployment-step_runner adapter for one human approval stage."""
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        verdict = evaluate_deployment_stage_approval(conn, run_id=run_id)
    finally:
        conn.close()
    if verdict.satisfied:
        return 0, ""
    if verdict.resolution_action == "reject":
        return 1, (
            f"deployment stage {stage_name!r} was rejected through "
            f"decision request {verdict.request_id}"
        )
    print(f"Awaiting Inbox decision {verdict.request_id} for stage '{stage_name}'")
    return -2, ""


__all__ = [
    "deployment_stage_decision",
    "deployment_stage_is_approved",
    "dispatch_deployment_stage_approval",
    "evaluate_deployment_stage_approval",
    "emit_deployment_completion",
]
