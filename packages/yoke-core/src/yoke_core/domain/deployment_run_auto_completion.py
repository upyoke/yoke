"""Finish a delivered run after its last durable QA or approval settlement.

Only control-plane stages may be advanced here. External step runners remain
the deployment driver's work; an absent receipt or unsettled subject leaves
the run at its recorded stage with a named recovery.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import iso8601_now


@dataclass(frozen=True)
class CompletionAttempt:
    completed: bool = False
    waiting: str = ""
    failure: str = ""


def _row_value(row: Any, name: str, index: int) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


def _approved(conn: Any, run_id: str, stage: str) -> bool:
    row = conn.execute(
        "SELECT status,resolution_action,consumed_at,subject_context "
        "FROM decision_requests "
        "WHERE subject_type='deployment_stage' AND subject_key=%s "
        "ORDER BY id DESC LIMIT 1",
        (f"{run_id}:{stage}",),
    ).fetchone()
    if (
        row is None
        or _row_value(row, "status", 0) != "resolved"
        or _row_value(row, "resolution_action", 1) != "approve"
        or _row_value(row, "consumed_at", 2) is not None
    ):
        return False
    run = conn.execute(
        "SELECT flow,release_lineage FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if run is None:
        return False
    raw_context = _row_value(row, "subject_context", 3)
    try:
        context = (
            dict(raw_context)
            if isinstance(raw_context, Mapping)
            else json.loads(str(raw_context))
        )
    except (TypeError, ValueError):
        return False
    return bool(
        isinstance(context, dict)
        and context.get("run_id") == run_id
        and context.get("stage") == stage
        and isinstance(context.get("flow"), dict)
        and context["flow"].get("id") == _row_value(run, "flow", 0)
        and isinstance(context.get("shipping"), dict)
        and context["shipping"].get("release_lineage")
        == (_row_value(run, "release_lineage", 1) or None)
    )


def _readiness(conn: Any, run_id: str) -> tuple[dict[str, Any] | None, str]:
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.deploy_lock import deploy_lock_key
    from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
    from yoke_core.domain.deployment_run_completion_preconditions import (
        unresolved_blocking_qa,
    )
    from yoke_core.domain.deployment_run_driver_attachment import (
        live_attachment_for_run,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )
    from yoke_core.domain.project_identity import resolve_project
    from yoke_core.domain.work_claim_targets import make_deploy_serialization_target

    row = conn.execute(
        "SELECT dr.project_id,dr.status,dr.current_stage,dr.target_tier,"
        "COALESCE(e.name,'') AS target_name,df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        "LEFT JOIN environments e ON e.id=dr.target_environment_id "
        "WHERE dr.id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        return None, f"deployment run {run_id} no longer exists"
    status = str(_row_value(row, "status", 1))
    if status == "succeeded":
        return None, "already succeeded"
    if status != "executing":
        return None, f"run status is {status}, not executing"
    project_id = int(_row_value(row, "project_id", 0))
    project = resolve_project(conn, project_id)
    assert project is not None
    claim = active_claim(
        conn, make_deploy_serialization_target(project_id, project.slug)
    )
    if claim is None:
        return None, (
            f"project deploy lock {deploy_lock_key(project.slug)} is unheld; "
            "acquire it and re-drive this run"
        )
    attached = live_attachment_for_run(conn, run_id_value=run_id, now=iso8601_now())
    if attached is not None:
        return None, f"live driver {attached.session_id} is already continuing this run"
    try:
        stages = json.loads(str(_row_value(row, "stages", 5)))
    except (TypeError, ValueError) as exc:
        return None, f"pinned flow stages are unreadable: {exc}"
    if not isinstance(stages, list) or not stages:
        return None, "pinned flow has no ordered stages"
    current = str(_row_value(row, "current_stage", 2) or "")
    names = [str(stage.get("name") or "") for stage in stages]
    if current == "complete":
        remaining = []
    elif current in names:
        remaining = stages[names.index(current) :]
    else:
        return None, f"current stage {current!r} is not in the pinned flow"
    for stage in remaining:
        name = str(stage.get("name") or "")
        runner = str(stage.get("step_runner") or "")
        if runner == "qa":
            outstanding = qa_stage_outstanding(conn, run_id=run_id, stage_name=name)
            if outstanding is None or outstanding.waiting:
                return None, f"QA stage {name!r} is not fully accepted"
        elif runner == "human-approval":
            if not _approved(conn, run_id, name):
                return None, f"approval stage {name!r} has no resolved approval"
        elif runner != "auto":
            return None, f"stage {name!r} still needs its {runner!r} driver"
    # Earlier QA is checked as well: a later approval must not make a red
    # item subject disappear merely because the stage cursor moved on.
    for stage in stages:
        if stage.get("step_runner") == "human-approval":
            name = str(stage.get("name") or "")
            if not _approved(conn, run_id, name):
                return None, f"approval stage {name!r} has no resolved approval"
        if stage.get("step_runner") != "qa":
            continue
        name = str(stage.get("name") or "")
        outstanding = qa_stage_outstanding(conn, run_id=run_id, stage_name=name)
        if outstanding is None or outstanding.waiting:
            return None, f"QA stage {name!r} is not fully accepted"
    unresolved = unresolved_blocking_qa(conn, run_id)
    if unresolved:
        return None, f"blocking QA remains: {'; '.join(unresolved)}"
    shared = any(
        stage.get("step_runner") == "human-approval"
        or (stage.get("step_runner") == "qa" and stage.get("scope") == "run")
        for stage in stages
    )
    members = conn.execute(
        "SELECT dri.item_id,dri.delivery_intent,i.status FROM deployment_run_items dri "
        "JOIN items i ON i.id=dri.item_id WHERE dri.run_id=%s ORDER BY dri.item_id",
        (run_id,),
    ).fetchall()
    for member in members:
        item_id = int(_row_value(member, "item_id", 0))
        if str(_row_value(member, "delivery_intent", 1) or "") != "final":
            continue
        item_status = str(_row_value(member, "status", 2) or "")
        if shared:
            if item_status not in {"release", "done"} or not satisfied_delivery_member(
                conn, item_id=item_id, run_id=run_id
            ):
                return None, f"final member {item_id} still owes item delivery or QA"
        elif item_status != "done":
            return None, f"final member {item_id} has not independently closed"
    return {
        "members": [int(_row_value(member, "item_id", 0)) for member in members],
        "delivered_to": str(
            _row_value(row, "target_name", 4) or _row_value(row, "target_tier", 3) or ""
        ),
        "remaining": [str(stage["name"]) for stage in remaining],
    }, ""


def finish_ready_run(conn: Any, run_id: str) -> CompletionAttempt:
    """Adopt settled evidence once, using the existing succeeded close-out.

    Call after the settlement transaction commits. An attached driver owns
    its continuation; a detached one can be finished by the serving control
    plane while the project's deploy claim still serializes the release.
    """
    from yoke_core.domain.backlog_item_db_writes import _update_item_multi
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    try:
        ready, reason = _readiness(conn, run_id)
        if ready is None:
            return CompletionAttempt(waiting=reason)
        for stage in ready["remaining"]:
            for item_id in ready["members"]:
                _update_item_multi(conn, item_id, {"deploy_stage": stage}, commit=False)
            conn.execute(
                "UPDATE deployment_runs SET current_stage=%s "
                "WHERE id=%s AND status='executing'",
                (stage, run_id),
            )
        for item_id in ready["members"]:
            fields = {"deploy_stage": "complete"}
            if ready["delivered_to"]:
                fields["deployed_to"] = ready["delivered_to"]
            _update_item_multi(conn, item_id, fields, commit=False)
        conn.execute(
            "UPDATE deployment_runs SET current_stage='complete' "
            "WHERE id=%s AND status='executing'",
            (run_id,),
        )
        conn.commit()
        refusal = cmd_update(run_id, "status", "succeeded")
        if refusal:
            return CompletionAttempt(
                failure=f"{refusal}; re-drive {run_id} under its project deploy lock"
            )
        return CompletionAttempt(completed=True)
    except Exception as exc:  # noqa: BLE001 - settlement remains durable
        conn.rollback()
        return CompletionAttempt(
            failure=(
                f"automatic completion of {run_id} failed: {exc}; "
                f"re-drive {run_id} under its project deploy lock"
            )
        )


def continue_after_settlement(
    conn: Any, run_id: str, *, notify_recovery: bool = True
) -> CompletionAttempt:
    """Attempt completion and durably address a refusal to the run's seat."""
    result = finish_ready_run(conn, run_id)
    if not notify_recovery:
        return result
    detail = result.failure or (
        result.waiting if "deploy lock" in result.waiting else ""
    )
    if not detail:
        return result
    from yoke_core.domain.deployment_run_driver_notice import push_run_scoped_notice
    from yoke_core.domain.project_identity import resolve_project

    key = hashlib.sha256(detail.encode()).hexdigest()[:16]
    try:
        row = conn.execute(
            "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()
        if row is None:
            print(detail)
            return result
        project = resolve_project(conn, int(_row_value(row, "project_id", 0)))
        if project is None:
            print(detail)
            return result
        delivered = push_run_scoped_notice(
            conn,
            project_id=project.id,
            body_for_route=lambda _route: (
                f"Deployment run {run_id} did not finish automatically: {detail}. "
                f"Read `yoke deployment-runs get {run_id}` before recovery."
            ),
            idempotency_key=f"deployment-run-completion-recovery:{run_id}:{key}",
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - retain the settled obligation
        conn.rollback()
        print(f"{detail}; recovery notice failed: {exc}")
        return result
    if not delivered:
        print(f"{detail}; no deploy driver or steering seat received recovery")
    return result


__all__ = ["CompletionAttempt", "continue_after_settlement", "finish_ready_run"]
