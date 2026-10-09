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
    released = False
    if outcome == "blocked" and member is not None:
        from yoke_core.domain.deployment_qa_failure_handoff import (
            notify_member_qa_failure,
        )

        handoff = notify_member_qa_failure(
            conn, run_id=run_id, stage=stage, item_id=member, status=status
        )
        released = handoff.startswith("released:")
        if handoff.startswith(("failed:", "unaddressed:")):
            print(
                f"Run {run_id} stage {stage!r} member {render_item_ref(conn, member)}: {handoff}"
            )
    completion_failure = ""
    if released or outcome in {"passed", "discharged"}:
        from yoke_core.domain.deployment_run_auto_completion import (
            continue_after_settlement,
        )

        attempt = continue_after_settlement(conn, run_id, notify_recovery=False)
        if attempt.completed:
            return status
        completion_failure = attempt.failure
        if member is not None:
            owing = members_still_owing(conn, run_id=run_id, stage=stage)
            if owing is None:
                completion_failure = completion_failure or (
                    "qa_stage_outstanding_unavailable: cannot determine remaining "
                    "stage subjects; read the run and retry its QA settlement"
                )
            elif owing and not completion_failure:
                # One member passing is report state; notify only when the
                # stage settles, goes red, or its continuation cannot finish.
                return status
    from yoke_core.domain.deployment_run_driver_notice import push_run_scoped_notice
    from yoke_core.domain.project_identity import resolve_project

    project = resolve_project(conn, int(status_project_id(conn, run_id)))
    notice_facts = (status.get("reasons") or (), completion_failure)
    key = (
        f"deployment-qa-continuation:{run_id}:{stage}:"
        f"{member if member is not None else 'run'}:"
        f"{status.get('target_digest') or ''}:{outcome}:"
        f"{hashlib.sha256(repr(notice_facts).encode()).hexdigest()[:12]}"
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
            blockers=""
            if released
            else "; ".join(str(reason) for reason in status.get("reasons") or ()),
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
        f"Deployment run {run_id} QA stage {stage!r}: "
        + (
            recovery
            if completion_failure
            else f"settled {outcome} against its frozen target. "
        )
        + f"{'Remaining blockers: ' + blockers + '. ' if blockers else ''}"
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
    "members_still_owing",
    "settle_execution",
    "settle_subject",
]
