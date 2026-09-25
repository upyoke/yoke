"""Act on a deployment run stage decision the moment it is answered.

An answered stage used to change nothing about its run: the decision row
resolved, and the run stayed ``executing`` at the same stage until somebody
happened to re-execute it. An approve stalled indefinitely; a rejection was
worse in kind, because the run kept presenting as in flight while a person had
already refused it.

The runner still holds its authority. ``deployment_run_approval`` states that
the deployment runner consumes the resolved decision and remains the only
surface that advances run and member-item deployment state, and nothing here
reverses that -- a resolve call has no repo checkout, no candidate revision, no
deploy lock and no budget for a multi-minute release, which is the reason that
authority sits with the driver in the first place. So the two answers are acted
on differently, because they are different facts:

* An approve still has a release to run, so this wakes the project's
  deploy-lock driver (its steering seat when no session holds the lock) with
  the recipe that re-enters the runner. Every advance remains the runner's.
* A rejection has nothing left to advance. Waking somebody would send them to
  a dead end, and until they went the run would keep lying about being in
  flight, so recording the rejection closes the run here. Closing a run is not
  advancing one: ``deployment_runs.terminalize`` already moves an active run to
  a terminal status under a row lock with an audit event and no deploy lock,
  and this is that same close with the decision as its reason.

The wake reuses :mod:`yoke_core.domain.deployment_run_driver_notice`, the same
recipient rule and delivery contract a waiting run-scoped QA stage uses, rather
than minting a second wake path for a second decision kind.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from yoke_core.domain.deployment_run_driver_notice import (
    DRIVER,
    push_run_scoped_notice,
)

#: A rejected stage closes its run as ``failed`` rather than ``cancelled`` so
#: that this path and a re-execute of the same rejected stage give one answer:
#: the pipeline's own ``fail_pipeline_stage`` records ``failed`` for exactly
#: this input, a stage whose approval came back rejected.
REJECTED_RUN_DISPOSITION = "failed"


def _stage_identity(request: dict[str, Any]) -> tuple[str, str]:
    """The run and stage this request was raised on.

    Read from the frozen subject context, falling back to the subject key it
    was built from. A request naming neither cannot be acted on at all, and
    says so rather than resolving into silence -- the same refusal
    :mod:`yoke_core.domain.decision_request_subject_state` makes when it
    cannot verify the stage a withdrawal would moot.
    """
    context = request.get("subject_context") or {}
    parts = str(request["subject_key"]).rsplit(":", 1)
    run_id = str(context.get("run_id") or parts[0]).strip()
    stage = str(context.get("stage") or (parts[1] if len(parts) == 2 else "")).strip()
    if not run_id or not stage:
        raise ValueError(
            f"decision request {request['id']} names no verifiable deployment "
            "stage, so its answer cannot be acted on; read the request with "
            f"`yoke inbox decisions get {request['id']}`"
        )
    return run_id, stage


def stage_subject_label(request: dict[str, Any]) -> str:
    """Name the subject for a degraded-delivery report."""
    run_id, stage = _stage_identity(request)
    return f"deployment run {run_id} stage {stage!r}"


def stage_decision_idempotency_key(
    run_id: str, stage: str, request_id: int, action: str
) -> str:
    """One notice per run, stage, request and answer.

    Keyed by the answer as well as the request so a later, different decision
    on the same stage is its own notice rather than being absorbed by an
    earlier one, while a retried delivery of the same answer stays single.
    """
    return f"deployment-stage-decision:{run_id}:{stage}:{request_id}:{action}"


def drive_recipe(run_id: str, project_slug: str, *, holds_lock: bool) -> str:
    """The commands that re-enter the runner on *run_id*, one per line.

    Rendered by the modules that own them -- :mod:`yoke_core.domain.deploy_lock`
    for the lock creating or executing a run requires, and
    :func:`deploy_pipeline_environment.watch_deploy_command` for the driver
    itself -- so the recipe cannot drift from what those surfaces accept. A
    recipient that already holds the lock is not told to take it again.
    """
    from yoke_core.domain.deploy_lock import acquire_command, release_command
    from yoke_core.domain.deploy_pipeline_environment import watch_deploy_command

    drive = f"  {watch_deploy_command(run_id)}"
    if holds_lock:
        return drive
    return "\n".join(
        (
            f"  {acquire_command(project_slug)}",
            drive,
            f"  {release_command(project_slug)}",
        )
    )


def stage_decision_message(
    *,
    run_id: str,
    stage: str,
    request_id: int,
    project_slug: str,
    route: str,
    completion_failure: str = "",
) -> str:
    """Say what was approved, and give a recipe this recipient can run."""
    holds_lock = route == DRIVER
    addressed = (
        "you hold this project's deploy lock"
        if holds_lock
        else (
            "no session holds this project's deploy lock, so this reaches its "
            "steering seat"
        )
    )
    recipe = drive_recipe(run_id, project_slug, holds_lock=holds_lock)
    recovery = (
        f"Automatic completion failed: {completion_failure}. "
        if completion_failure
        else ""
    )
    return (
        f"Deployment run {run_id} stage {stage!r} is APPROVED: decision "
        f"request {request_id} resolved approve. {recovery}The run still needs "
        "its pinned runner for remaining work, and "
        f"{addressed}. Re-enter the runner on the same run id:\n"
        f"{recipe}\n"
        "The recorded answer is what the stage reads, so this continues the "
        "release rather than asking anyone again. Check "
        f"`yoke deployment-runs get {run_id}` for the current state."
    )


def apply_deployment_stage_decision(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    actor_id: int,
    note: Optional[str],
    stamp: str,
    session_id: str = "",
) -> None:
    """Close a rejected run; leave an approved one for the runner."""
    if action != "reject":
        return
    from yoke_core.domain.deployment_run_terminalization import (
        RunTerminalizationRejected,
        terminalize_run_on,
    )

    run_id, stage = _stage_identity(request)
    reason = f"stage {stage!r} was rejected through decision request {request['id']}"
    if (note or "").strip():
        reason = f"{reason}: {note.strip()}"
    try:
        terminalize_run_on(
            conn,
            run_id,
            disposition=REJECTED_RUN_DISPOSITION,
            reason=reason,
            actor_id=actor_id,
            session_id=session_id,
            terminalized_at=stamp,
        )
    except RunTerminalizationRejected:
        # The run is already terminal, which is the state the rejection wanted
        # it in. A redundant close is not a reason to refuse the decision.
        return


def notify_deployment_stage_decision(
    conn: Any,
    request: dict[str, Any],
    *,
    action: str,
    note: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Wake the driver for an approved stage. ``None`` when nobody is owed one.

    A rejection is already closed by
    :func:`apply_deployment_stage_decision`, so there is no run left to drive
    and nobody to tell -- which is different from having somebody to tell and
    failing to find them, and is reported as such.
    """
    if action != "approve":
        return None
    from yoke_core.domain.project_identity import resolve_project

    run_id, stage = _stage_identity(request)
    from yoke_core.domain.deployment_run_auto_completion import (
        continue_after_settlement,
    )

    attempt = continue_after_settlement(conn, run_id, notify_recovery=False)
    if attempt.completed:
        return None
    project_id = request.get("project_id")
    if project_id is None:
        return ""
    identity = resolve_project(conn, int(project_id), required=False)
    if identity is None:
        return ""
    return push_run_scoped_notice(
        conn,
        project_id=int(project_id),
        body_for_route=lambda route: stage_decision_message(
            run_id=run_id,
            stage=stage,
            request_id=int(request["id"]),
            project_slug=identity.slug,
            route=route,
            completion_failure=attempt.failure,
        ),
        idempotency_key=stage_decision_idempotency_key(
            run_id, stage, int(request["id"]), action
        ),
        now=now,
    )


__all__ = [
    "REJECTED_RUN_DISPOSITION",
    "apply_deployment_stage_decision",
    "drive_recipe",
    "notify_deployment_stage_decision",
    "stage_decision_idempotency_key",
    "stage_decision_message",
    "stage_subject_label",
]
