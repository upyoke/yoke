"""Finish a delivered run after its last durable QA or approval settlement.

Only control-plane stages may be advanced here. External step runners remain
the deployment driver's work; an absent receipt or unsettled subject leaves
the run at its recorded stage with a named recovery.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.schema_read_scope import composition_operation


@dataclass(frozen=True)
class CompletionAttempt:
    completed: bool = False
    waiting: str = ""
    failure: str = ""


_STAGE_SETTLEMENT_RUN: ContextVar[str] = ContextVar(
    "stage_settlement_continues_run", default=""
)


@contextmanager
def stage_settlement_continues(run_id: str) -> Iterator[None]:
    """Defer this run's completion to the QA stage settlement that follows.

    A member close-out inside the settlement's gate would otherwise attempt
    completion, and walk the stage, once more before the settlement does.
    """
    token = _STAGE_SETTLEMENT_RUN.set(run_id)
    try:
        yield
    finally:
        _STAGE_SETTLEMENT_RUN.reset(token)


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


def _drive(run_id: str) -> str:
    from yoke_core.domain.deploy_pipeline_environment import watch_deploy_command

    return watch_deploy_command(run_id)


def _qa_waiting(conn: Any, run_id: str, stage_name: str) -> bool:
    from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding

    outstanding = qa_stage_outstanding(
        conn, run_id=run_id, stage_name=stage_name, stop_at_first_waiting=True
    )
    return outstanding is None or bool(outstanding.waiting)


@composition_operation
def _readiness(
    conn: Any, run_id: str, accepted_qa_stage: str = ""
) -> tuple[dict[str, Any] | None, str]:
    from yoke_core.domain.deployment_run_completion_preconditions import (
        unresolved_blocking_qa,
    )
    from yoke_core.domain.deployment_run_driver_attachment import (
        live_attachment_for_run,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

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
    current_stage = str(_row_value(row, "current_stage", 2) or "")
    attached = live_attachment_for_run(conn, run_id_value=run_id, now=utc_now())
    if attached is not None and current_stage != "complete":
        return None, f"live driver {attached.session_id} is already continuing this run"
    try:
        stages = json.loads(str(_row_value(row, "stages", 5)))
    except (TypeError, ValueError) as exc:
        return None, f"pinned flow stages are unreadable: {exc}"
    if not isinstance(stages, list) or not stages:
        return None, "pinned flow has no ordered stages"
    current = current_stage
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
            if name != accepted_qa_stage and _qa_waiting(conn, run_id, name):
                return None, f"QA stage {name!r} is not fully accepted"
        elif runner == "human-approval":
            if not _approved(conn, run_id, name):
                return None, f"approval stage {name!r} has no resolved approval"
        elif runner != "auto":
            return None, f"stage {name!r} still needs its {runner!r} driver"
    # Earlier stages are checked as well: a later approval must not make a red
    # item subject disappear merely because the stage cursor moved on.
    for stage in stages[: len(stages) - len(remaining)]:
        name = str(stage.get("name") or "")
        runner = stage.get("step_runner")
        if runner == "human-approval" and not _approved(conn, run_id, name):
            return None, f"approval stage {name!r} has no resolved approval"
        if (
            runner == "qa"
            and name != accepted_qa_stage
            and _qa_waiting(conn, run_id, name)
        ):
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
        from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run
        from yoke_core.domain.deployment_run_other_target_members import (
            owes_only_other_targets,
            member_completion_blocker,
        )

        if supplemental_qa_run(conn, run_id=run_id, item_id=item_id):
            continue
        item_status = str(_row_value(member, "status", 2) or "")
        if shared:
            if item_status not in {"release", "done"} or not satisfied_delivery_member(
                conn, item_id=item_id, run_id=run_id
            ):
                return (
                    None,
                    member_completion_blocker(conn, run_id=run_id, item_id=item_id),
                )
        elif item_status != "done" and not owes_only_other_targets(
            conn, run_id=run_id, item_id=item_id
        ):
            return (
                None,
                member_completion_blocker(conn, run_id=run_id, item_id=item_id),
            )
    return {
        "members": [int(_row_value(member, "item_id", 0)) for member in members],
        "delivered_to": str(
            _row_value(row, "target_name", 4) or _row_value(row, "target_tier", 3) or ""
        ),
        "remaining": [str(stage["name"]) for stage in remaining],
    }, ""


def finish_ready_run(
    conn: Any, run_id: str, *, accepted_qa_stage: str = ""
) -> CompletionAttempt:
    """Adopt settled evidence once, using the existing succeeded close-out.

    Call after the settlement transaction commits. ``accepted_qa_stage``
    names a QA stage the caller just read as owing nothing, so it is not
    walked again. An attached driver owns
    its continuation; a detached one is finished here by the serving
    control plane, and the run's target occupancy still keeps any other
    run off its servers until it is terminal.
    """
    from yoke_core.domain.backlog_item_db_writes import _update_item_multi
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
    from yoke_core.domain.deployment_run_stage_entry import set_current_stage

    try:
        ready, reason = _readiness(conn, run_id, accepted_qa_stage)
        if ready is None:
            return CompletionAttempt(waiting=reason)
        for stage in ready["remaining"]:
            for item_id in ready["members"]:
                _update_item_multi(conn, item_id, {"deploy_stage": stage}, commit=False)
            set_current_stage(conn, run_id, stage, only_executing=True)
        for item_id in ready["members"]:
            fields = {"deploy_stage": "complete"}
            if ready["delivered_to"]:
                fields["deployed_to"] = ready["delivered_to"]
            _update_item_multi(conn, item_id, fields, commit=False)
        set_current_stage(conn, run_id, "complete", only_executing=True)
        conn.commit()
        refusal = cmd_update(run_id, "status", "succeeded")
        if refusal:
            return CompletionAttempt(
                failure=f"{refusal}; re-drive it with `{_drive(run_id)}`"
            )
        return CompletionAttempt(completed=True)
    except Exception as exc:  # noqa: BLE001 - settlement remains durable
        conn.rollback()
        return CompletionAttempt(
            failure=(
                f"automatic completion of {run_id} failed: {exc}; "
                f"re-drive it with `{_drive(run_id)}`"
            )
        )


def continue_after_settlement(
    conn: Any,
    run_id: str,
    *,
    notify_recovery: bool = True,
    accepted_qa_stage: str = "",
) -> CompletionAttempt:
    """Attempt completion and durably address a refusal to the run's seat."""
    if _STAGE_SETTLEMENT_RUN.get() == run_id:
        return CompletionAttempt(waiting="its QA stage settlement continues it")
    result = finish_ready_run(conn, run_id, accepted_qa_stage=accepted_qa_stage)
    if not notify_recovery:
        return result
    detail = result.failure
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
            run_id=run_id,
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


__all__ = [
    "CompletionAttempt",
    "continue_after_settlement",
    "finish_ready_run",
    "stage_settlement_continues",
]
