"""Settle a scoped deployment QA gate when its evidence becomes final.

The deploy runner still owns external stages. QA evidence and human decisions
are control-plane writes, so their gate can be settled here without waiting
for the runner to happen to check the same stage again.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from yoke_core.domain.project_identity import render_item_ref


def _current_execution(conn, execution_id):
    from yoke_core.domain.deployment_run_qa_transfer import qa_ownership_write
    from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    # Takeover locks membership/run before executions. Use the same order and
    # release only this attempt's locks if ownership changed while acquiring it.
    class OwnerChanged(Exception):
        pass

    for _attempt in range(3):
        try:
            with qa_ownership_write(conn):
                before = select_plan_execution(conn, execution_id, lock=False)
                owner = before.get("deployment_run_id")
                if owner:
                    lock_run_with_stable_membership(conn, str(owner))
                current = select_plan_execution(conn, execution_id, lock=True)
                if current.get("deployment_run_id") != owner:
                    raise OwnerChanged
                return current
        except OwnerChanged:
            continue
    raise ValueError(
        "qa_execution_owner_changed: QA ownership changed during settlement; "
        "retry completion using the same execution ID"
    )


def settle_execution(conn: Any, execution: Mapping[str, Any]) -> dict[str, Any] | None:
    """Settle the active stage for one completed, target-bound execution."""
    if not execution.get("deployment_stage"):
        return None
    execution = _current_execution(conn, str(execution["id"]))
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
    from yoke_core.domain.qa_execution_environment_target import target_digest

    member = execution.get("deployment_member_item_id")
    from yoke_core.domain.deployment_qa_shared_plans import (
        execution_subject,
    )

    subject = execution_subject(conn, execution)
    frozen_digest = target_digest(deployment_qa_execution_target(conn, subject))
    if str(execution.get("execution_target_digest") or "") != frozen_digest:
        raise ValueError(
            f"QA execution {execution['id']} targets a different deployment "
            f"candidate than run {run_id} stage {stage!r}; execute this "
            "stage's cases against its frozen target"
        )
    if subject.get("shared_plan"):
        return settle_plan_group(conn, subject)
    return settle_subject(
        conn,
        run_id=run_id,
        stage=stage,
        member=int(member) if member is not None else None,
    )


SETTLED_OUTCOMES = frozenset({"passed", "discharged", "rejected", "blocked"})


def settle_plan_group(conn: Any, subject: Mapping[str, Any]) -> dict[str, Any]:
    """Settle one plan group; a failure tells the run's session, never a member."""
    from yoke_core.domain.deployment_qa_plan_group_dispatch import (
        FAILED_OUTCOMES,
        notify_plan_group_failure,
        settle_group,
    )
    from yoke_core.domain.deployment_qa_plan_groups import group_for_target

    run_id, stage = str(subject["id"]), str(subject["stage"]["name"])
    status = settle_group(conn, subject)
    outcome = str(status.get("outcome") or "")
    if outcome in FAILED_OUTCOMES:
        group = group_for_target(conn, run_id, subject["shared_target"])
        if group is not None:
            notify_plan_group_failure(
                conn, run_id=run_id, stage_name=stage, group=group,
                project_id=int(status_project_id(conn, run_id)),
                reasons=list(status.get("reasons") or ()),
                item_refs=lambda member: render_item_ref(conn, member),
            )
        return status
    if outcome not in SETTLED_OUTCOMES:
        return status
    return continue_settled_stage(
        conn, run_id=run_id, stage=stage, member=None, status=status,
        released=False, item_scoped=True,
    )


def settle_subject(
    conn: Any, *, run_id: str, stage: str, member: int | None
) -> dict[str, Any]:
    """Converge acceptance and request the existing run's continuation."""
    status, released = settle_acceptance(
        conn, run_id=run_id, stage=stage, member=member
    )
    if str(status.get("outcome") or "") not in SETTLED_OUTCOMES:
        return status
    return continue_settled_stage(
        conn,
        run_id=run_id,
        stage=stage,
        member=member,
        status=status,
        released=released,
    )


def settle_acceptance(
    conn: Any, *, run_id: str, stage: str, member: int | None
) -> tuple[dict[str, Any], bool]:
    """Converge one subject's acceptance; True when a failure released its member."""
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
    from yoke_core.domain.deployment_run_auto_completion import (
        stage_settlement_continues,
    )

    # Every caller continues the run once after acceptance converges.
    with stage_settlement_continues(run_id):
        status = deployment_qa_stage_status(
            conn, run_id=run_id, stage_name=stage, member_item_id=member
        )
    outcome = str(status.get("outcome") or "")
    if outcome not in SETTLED_OUTCOMES:
        return status, False
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
    return status, released


def continue_settled_stage(
    conn: Any,
    *,
    run_id: str,
    stage: str,
    member: int | None,
    status: dict[str, Any],
    released: bool,
    item_scoped: bool = False,
) -> dict[str, Any]:
    """Request the run's continuation after a subject settled, or report why not.

    ``item_scoped`` marks a plan group: memberless, but its stage still waits
    on members and other groups before the run continues.
    """
    item_scoped = item_scoped or member is not None
    outcome = str(status.get("outcome") or "")
    completion_failure = ""
    if released or outcome in {"passed", "discharged"}:
        from yoke_core.domain.deployment_run_auto_completion import (
            continue_after_settlement,
        )

        # A member's stage is read once: while a sibling still owes QA the
        # run cannot complete, and once none does completion skips the stage.
        waiting = (
            stage_waiting(conn, run_id=run_id, stage=stage) if item_scoped else False
        )
        if waiting:
            # One member passing is report state; notify only when the
            # stage settles, goes red, or its continuation cannot finish.
            return status
        if waiting is None:
            completion_failure = (
                "qa_stage_outstanding_unavailable: cannot determine remaining "
                "stage subjects; read the run and retry its QA settlement"
            )
        else:
            attempt = continue_after_settlement(
                conn,
                run_id,
                notify_recovery=False,
                accepted_qa_stage=stage if item_scoped else "",
            )
            if attempt.completed:
                return status
            completion_failure = attempt.failure
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
        run_id=run_id,
        project_id=project.id,
        body_for_route=lambda _route: continuation_message(
            run_id=run_id,
            stage=stage,
            outcome=outcome,
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
            f"The outcome is durable; re-drive the same run with `yoke watch deploy -- {run_id}`."
        )
    return status


def stage_waiting(conn: Any, *, run_id: str, stage: str) -> bool | None:
    """Whether any subject still owes the stage; ``None`` when that cannot be read."""
    from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding

    outstanding = qa_stage_outstanding(
        conn, run_id=run_id, stage_name=stage, stop_at_first_waiting=True
    )
    return None if outstanding is None else bool(outstanding.waiting)


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
    completion_failure: str = "",
    blockers: str = "",
) -> str:
    from yoke_core.domain.deployment_stage_decision_effect import drive_recipe

    recipe = drive_recipe(run_id)
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
        f"its pinned runner:\n{recipe}\n"
        "Read the run and its live driver attachment first. If that driver "
        "is still running, continue its existing watcher; otherwise re-enter "
        "this run. The runner adopts recorded QA and completed stages "
        "without starting a second driver or replaying passed work. "
        f"Read `yoke deployment-runs get {run_id}` before acting."
    )


__all__ = [
    "SETTLED_OUTCOMES",
    "continuation_message",
    "continue_settled_stage",
    "settle_acceptance",
    "settle_execution",
    "settle_subject",
    "stage_waiting",
]
