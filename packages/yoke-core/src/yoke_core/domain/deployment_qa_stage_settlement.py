"""Settle a scoped deployment QA gate when its evidence becomes final.

The deploy runner still owns external stages. QA evidence and human decisions
are control-plane writes, so their gate can be settled here without waiting
for the runner to happen to check the same stage again.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from yoke_core.domain.project_identity import render_item_ref


def settle_execution(conn: Any, execution: Mapping[str, Any]) -> dict[str, Any] | None:
    """Settle the active stage for one completed, target-bound execution."""
    run_id = str(execution.get("deployment_run_id") or "")
    stage = str(execution.get("deployment_stage") or "")
    if not run_id or not stage or execution.get("state") != "completed":
        return None
    run = conn.execute(
        "SELECT status,current_stage FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"deployment run {run_id!r} no longer exists")
    status = str(run["status"] if hasattr(run, "keys") else run[0])
    current_stage = str(run["current_stage"] if hasattr(run, "keys") else run[1])
    if status != "executing" or current_stage != stage:
        # A repeated completion after the pinned runner advanced is an
        # idempotent read of earlier evidence, not permission to reopen it.
        return None
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.qa_execution_environment_target import target_digest

    member = execution.get("deployment_member_item_id")
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=stage,
        member_item_id=int(member) if member is not None else None,
    )
    frozen_digest = target_digest(deployment_qa_execution_target(conn, subject))
    if str(execution.get("execution_target_digest") or "") != frozen_digest:
        raise ValueError(
            f"QA execution {execution['id']} targets a different deployment "
            f"candidate than run {run_id} stage {stage!r}; execute this "
            "stage's cases against its frozen target"
        )
    return settle_subject(
        conn,
        run_id=run_id,
        stage=stage,
        member=int(member) if member is not None else None,
    )


def settle_subject(
    conn: Any, *, run_id: str, stage: str, member: int | None
) -> dict[str, Any]:
    """Converge acceptance and request the existing run's continuation."""
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

    status = deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=stage, member_item_id=member
    )
    outcome = str(status.get("outcome") or "")
    if outcome not in {"passed", "discharged", "rejected", "blocked"}:
        return status
    conn.commit()
    if outcome == "blocked" and member is not None:
        from yoke_core.domain.deployment_qa_failure_handoff import (
            notify_member_qa_failure,
        )

        handoff = notify_member_qa_failure(
            conn, run_id=run_id, stage=stage, item_id=member, status=status
        )
        if handoff.startswith(("failed:", "unaddressed:")):
            print(
                f"Run {run_id} stage {stage!r} member {render_item_ref(conn, member)}: {handoff}"
            )
    completion_failure = ""
    if outcome in {"passed", "discharged"}:
        from yoke_core.domain.deployment_run_auto_completion import (
            continue_after_settlement,
        )

        attempt = continue_after_settlement(conn, run_id, notify_recovery=False)
        if attempt.completed:
            return status
        completion_failure = attempt.failure
        if member is not None:
            owing = members_still_owing(conn, run_id=run_id, stage=stage)
            if owing != ():
                # One member's acceptance is not the stage's: the gate stays
                # current until every member settles, so there is nothing
                # to re-drive and the notice says whose QA it still waits on.
                _notify_member_settled(
                    conn,
                    run_id=run_id,
                    stage=stage,
                    member=member,
                    outcome=outcome,
                    owing=owing,
                    status=status,
                    completion_failure=completion_failure,
                )
                return status
    from yoke_core.domain.deployment_run_driver_notice import push_run_scoped_notice
    from yoke_core.domain.project_identity import resolve_project

    project = resolve_project(conn, int(status_project_id(conn, run_id)))
    key = (
        f"deployment-qa-continuation:{run_id}:{stage}:"
        f"{member if member is not None else 'run'}:"
        f"{status.get('target_digest') or ''}:{outcome}:"
        f"{hashlib.sha256(repr(status.get('reasons') or ()).encode()).hexdigest()[:12]}"
    )
    delivery = push_run_scoped_notice(
        conn,
        project_id=project.id,
        body_for_route=lambda route: continuation_message(
            run_id=run_id,
            stage=stage,
            outcome=outcome,
            project_slug=project.slug,
            route=route,
            completion_failure=completion_failure,
            blockers="; ".join(str(reason) for reason in status.get("reasons") or ()),
        ),
        idempotency_key=key,
    )
    conn.commit()
    if not delivery:
        print(
            f"Run {run_id} stage {stage!r} settled {outcome}, but no deploy "
            "driver or covering steering seat could be reached. The QA "
            f"blockers are {status.get('reasons') or 'none reported'}. "
            "The outcome is durable; acquire the project deploy lock and re-drive "
            f"the same run with `yoke watch deploy -- {run_id}`."
        )
    return status


def members_still_owing(
    conn: Any, *, run_id: str, stage: str
) -> tuple[int | None, ...] | None:
    """Subjects the stage still waits on; ``None`` when that cannot be read."""
    from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding

    outstanding = qa_stage_outstanding(conn, run_id=run_id, stage_name=stage)
    return None if outstanding is None else outstanding.waiting_members


def _notify_member_settled(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member: int,
    outcome: str,
    owing: tuple[int | None, ...] | None,
    status: Mapping[str, Any],
    completion_failure: str,
) -> None:
    from yoke_core.domain.deployment_run_driver_notice import push_run_scoped_notice
    from yoke_core.domain.item_ref_render import render_item_refs
    from yoke_core.domain.project_identity import render_item_ref, resolve_project

    project = resolve_project(conn, int(status_project_id(conn, run_id)))
    ids = [int(value) for value in (member, *(owing or ())) if value is not None]
    refs = render_item_refs(conn, ids)
    owing_refs = (
        None
        if owing is None
        else [
            "the run"
            if value is None
            else (refs.get(int(value)) or render_item_ref(conn, int(value)))
            for value in owing
        ]
    )
    body = member_settled_message(
        run_id=run_id,
        stage=stage,
        member_ref=refs.get(member) or render_item_ref(conn, member),
        outcome=outcome,
        owing_refs=owing_refs,
        completion_failure=completion_failure,
    )
    owing_key = "unread" if owing is None else ",".join(map(str, owing))
    delivery = push_run_scoped_notice(
        conn,
        project_id=project.id,
        body_for_route=lambda _route: body,
        idempotency_key=(
            f"deployment-qa-member-settled:{run_id}:{stage}:{member}:"
            f"{status.get('target_digest') or ''}:{outcome}:{owing_key}"
        ),
    )
    conn.commit()
    if not delivery:
        print(body)


def member_settled_message(
    *,
    run_id: str,
    stage: str,
    member_ref: str,
    outcome: str,
    owing_refs: list[str] | None,
    completion_failure: str = "",
) -> str:
    """One member's QA settled; the stage's own gate is not known settled."""
    head = (
        f"Deployment run {run_id} QA stage {stage!r}: member {member_ref} "
        f"settled {outcome} against its frozen target."
    )
    failure = (
        f" Automatic completion failed: {completion_failure}."
        if completion_failure
        else ""
    )
    gate = f"`yoke deployment-runs stages {run_id}`"
    if owing_refs is None:
        return (
            f"{head} Which members still owe QA could not be read.{failure} "
            f"Read the live gate with {gate}: re-drive the run only once "
            "that shows the stage settled."
        )
    return (
        f"{head} The stage itself has not settled. Still owing QA: "
        f"{', '.join(owing_refs)}.{failure} There is nothing to re-drive: "
        "the stage settles when those members' QA is accepted, and the run "
        f"continues from there. Read the live gate with {gate}."
    )


def status_project_id(conn: Any, run_id: str) -> int:
    row = conn.execute(
        "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"deployment run {run_id!r} no longer exists")
    return int(row["project_id"] if hasattr(row, "keys") else row[0])


def continuation_message(
    *,
    run_id: str,
    stage: str,
    outcome: str,
    project_slug: str,
    route: str,
    completion_failure: str = "",
    blockers: str = "",
) -> str:
    from yoke_core.domain.deployment_run_driver_notice import DRIVER
    from yoke_core.domain.deployment_stage_decision_effect import drive_recipe

    recipe = drive_recipe(run_id, project_slug, holds_lock=route == DRIVER)
    recovery = (
        f"Automatic completion failed: {completion_failure}. "
        if completion_failure
        else ""
    )
    return (
        f"Deployment run {run_id} QA stage {stage!r} settled {outcome} "
        f"against its frozen target. {recovery}"
        f"{'Remaining blockers: ' + blockers + '. ' if blockers else ''}"
        "Continue this same run through "
        f"its pinned deploy-lock runner:\n{recipe}\n"
        "Read the run and its live driver attachment first. If that driver "
        "is still running, continue its existing watcher; otherwise re-enter "
        "this run. The runner adopts recorded QA and completed stages "
        "without starting a second driver or replaying passed work. "
        f"Read `yoke deployment-runs get {run_id}` before acting."
    )


__all__ = [
    "continuation_message",
    "member_settled_message",
    "members_still_owing",
    "settle_execution",
    "settle_subject",
]
