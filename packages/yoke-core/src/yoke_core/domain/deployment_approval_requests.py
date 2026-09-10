"""Decision-request adapter for a deployment run's human approval stage."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_release_effect import derive_release_effect
from yoke_core.domain.deployment_stage_position import stage_position
from yoke_core.domain.decision_requests import (
    create_decision_request,
    list_subject_requests,
)
from yoke_core.domain.events_bounded_emit import emit_bounded


#: The registered operation that derives one exact run stage's approval
#: verdict. Named here so the evaluator, its handler, and the pipeline
#: adapter all address the same operation.
EVALUATE_STAGE_APPROVAL_FUNCTION = "deployment_runs.stage_approval.evaluate"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _run(conn: Any, run_id: str, *, for_update: bool = False) -> dict[str, Any]:
    p = _p(conn)
    suffix = ""
    if for_update and db_backend.connection_is_postgres(conn):
        suffix = " FOR UPDATE OF dr"
    row = conn.execute(
        "SELECT dr.id, dr.project_id, dr.flow, df.name AS flow_name, "
        "dr.target_tier, dr.release_lineage, "
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
    expected: dict[str, Any],
) -> bool:
    context = request.get("subject_context")
    if not isinstance(context, dict):
        return False
    return (
        all(context.get(field) == expected[field] for field in expected)
        and request.get("consumed_at") is None
    )


def _batch_items(conn: Any, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT i.id, i.project_sequence, i.title, p.slug AS project, "
        "p.public_item_prefix FROM deployment_run_items dri "
        "JOIN items i ON i.id=dri.item_id "
        "JOIN projects p ON p.id=i.project_id "
        f"WHERE dri.run_id={_p(conn)} ORDER BY i.id",
        (run_id,),
    ).fetchall()
    return [
        {
            "item_id": int(row["id"]),
            "item_ref": format_item_ref(
                row["project"],
                row["public_item_prefix"],
                row["project_sequence"],
            ),
            "title": str(row["title"]),
        }
        for row in rows
    ]


def _deployment_subject_context(
    conn: Any,
    run: dict[str, Any],
    stage: str,
    target: str,
) -> dict[str, Any]:
    items = _batch_items(conn, str(run["id"]))
    lineage = str(run["release_lineage"] or "").strip() or None
    lineage_summary = f" under release lineage {lineage}" if lineage else ""
    return {
        "run_id": str(run["id"]),
        "flow": {"id": str(run["flow"]), "name": str(run["flow_name"])},
        "stage": stage,
        "stage_position": stage_position(run, stage),
        "batch": {"item_count": len(items), "items": items},
        "shipping": {
            "release_lineage": lineage,
            "target_environment": target,
            "summary": (f"{len(items)} item(s) ship to {target}{lineage_summary}."),
        },
    }


def _release_contents(conn: Any, run_id: str) -> dict[str, Any]:
    """Derive what this run actually carries, once, for a brand-new request.

    Run membership answers which items the pipeline owns, and an environment
    run owns none — so a card built from membership alone told an approver a
    release contained nothing while it shipped every change merged since the
    last one. The carried-work deriver already answers the real question from
    release lineage, and its result travels into the immutable snapshot here.

    This runs only on the path that creates a request. Re-evaluating a gate
    that already has a pending request must not shell out to git again, and a
    stored snapshot is never recomputed.
    """
    from yoke_core.domain.deployment_run_carried_work import (
        derive_carried_work_safely,
    )

    return derive_carried_work_safely(conn, run_id)


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
    stage: str,
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
):
    """Fail closed until an authorized approval resolves this run stage.

    *stage* names the exact stage the caller believes the run is waiting
    at, and a run standing somewhere else is refused rather than evaluated.
    A caller that let the run choose would evaluate whichever stage the run
    happened to reach, which is a different gate than the one it asked
    about.
    """
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

    requested_stage = str(stage or "").strip()
    if not requested_stage:
        raise ValueError("an exact stage name is required")
    run = _run(conn, run_id, for_update=True)
    if run["status"] != "executing" or not run["current_stage"]:
        raise ValueError(
            f"deployment run {run_id!r} is not waiting at an executing stage"
        )
    stage = str(run["current_stage"])
    if stage != requested_stage:
        raise ValueError(
            f"deployment run {run_id!r} is waiting at stage {stage!r}, not "
            f"{requested_stage!r}; re-read the run with "
            f"`yoke deployment-runs stages {run_id}` and evaluate the stage "
            "it is actually waiting at"
        )
    stages = parse_flow_stages(str(run["stages"]))
    resolution = resolve_approval(stages, stage)
    if not resolution.approved:
        raise ValueError(resolution.error or "stage does not accept approval")
    stage_def = next(entry for entry in stages if entry.name == stage)
    if "approvals" not in stage_def.config:
        raise ValueError(MISSING_STAGE_APPROVALS.format(name=stage))
    policy = parse_stage_approvals(
        stage_def.config.get("approvals"),
        path=f"stage {stage!r} approvals",
    )
    target = str(run["target_environment"] or run["target_tier"] or "merge-only")
    subject_context = _deployment_subject_context(conn, run, stage, target)
    waiting = "the stage is waiting for a human decision"
    verdict = verdict_from_request_history(
        conn,
        list_subject_requests(conn, "deployment_stage", f"{run_id}:{stage}"),
        snapshot_matches=lambda request: _matches_deployment_snapshot(
            request,
            {
                field: subject_context[field]
                for field in ("run_id", "flow", "stage", "batch", "shipping")
            },
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
    # Only now, with no request answering for this snapshot, is the release
    # content derived: the deriver reads git, and repeating it on every
    # pending-gate evaluation would pay for a fact the snapshot already froze.
    subject_context["carried"] = _release_contents(conn, run_id)
    # What resolving this stage actually does, read from the flow's runners,
    # its declared destination and the contents just derived -- never from the
    # flow's name or an empty batch. The title follows the classification, so
    # a gate that deploys nothing never reaches its approver as a deployment.
    effect = derive_release_effect(
        stages=stages,
        target_environment=run["target_environment"],
        target_tier=run["target_tier"],
        carried=subject_context["carried"],
        batch_item_count=int(subject_context["batch"]["item_count"]),
        stage=stage,
    )
    subject_context["release_effect"] = effect
    subject_context["title"] = effect["headline"]
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
            role_names=policy.roles,
        ),
        named_actor_ids=policy.actors,
        approval_mode=policy.mode,
        subject_context=subject_context,
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
) -> None:
    """Append one terminal run event in the caller's transaction.

    ``deployment_runs`` already owns whether the run succeeded or failed,
    so this event is a disposable record of a terminal fact rather than
    the fact itself. An unknown event name and a run id that resolves to
    nothing are still defects and still raise; a filtered severity or an
    events outage is logged instead, so telemetry cannot fail a pipeline
    whose run state is already written.
    """
    if event_name not in {"DeploymentRunSucceeded", "DeploymentRunFailed"}:
        raise ValueError(f"{event_name!r} is not a deployment completion event")
    run = _run(conn, run_id)
    event_context = dict(context)
    event_context["run_id"] = run_id
    emit_bounded(
        conn,
        event_name,
        durable_fact=(
            f"the run's terminal state is committed on deployment_runs — "
            f"read it with `yoke deployment-runs get {run_id}`"
        ),
        event_kind="lifecycle",
        event_type="deployment_run",
        source_type="system",
        severity="STATUS",
        outcome=outcome,
        project=str(run["project"]),
        context=event_context,
    )


__all__ = [
    "EVALUATE_STAGE_APPROVAL_FUNCTION",
    "deployment_stage_decision",
    "deployment_stage_is_approved",
    "evaluate_deployment_stage_approval",
    "emit_deployment_completion",
]
