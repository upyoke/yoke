"""Dispatch item-qa plan groups: create, gate once, and tell one session.

A plan group is run QA in shape: memberless rows on the run, settled as a
run-scoped subject. Dispatch launches nothing and wakes no member holder for
it. Pending groups reach the run's live driver, else the session that started
the run, else the steering seat, in one notice per set of pending groups; a
failed group sends one notice naming its report and its items, and that
session decides who fixes what.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_qa_plan_groups import (
    PlanGroup,
    attaching_members,
    run_groups,
)

PLAN_GROUPS_WAIT_PREFIX = "deployment-qa-stage-wait:"
PLAN_GROUP_FAILURE_PREFIX = "deployment-qa-plan-group-failure:"
#: A group that failed or whose acceptance was rejected: its failure notice.
FAILED_OUTCOMES = frozenset({"blocked", "rejected"})


def plan_group_writer(conn: Any, stage: Mapping, *, run_id: str):
    """The write that creates each owed group, for the cohort's run lock.

    None at a run-scoped stage. A refusal propagates by name.
    """
    if stage.get("scope") != "item":
        return None
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

    return lambda: ensure_groups(conn, str(run_id), str(stage["name"]))


def settle_group(conn: Any, subject: Mapping) -> dict:
    """Settle one group as its own run-scoped subject; a pass closes it."""
    from yoke_core.domain.deployment_qa_stage_gate import _settle_stage_status

    status = _settle_stage_status(
        conn,
        subject=subject,
        target=subject["shared_target"],
        run_id=str(subject["id"]),
        stage_name=str(subject["stage"]["name"]),
        member_item_id=None,
    )
    conn.commit()
    return status


def _plan_label(conn: Any, plan_id: int) -> str:
    row = conn.execute("SELECT slug FROM qa_plans WHERE id=%s", (int(plan_id),)).fetchone()
    return str(row["slug"] if hasattr(row, "keys") else row[0]) if row else str(plan_id)


def gate_plan_groups(
    conn: Any,
    stage: Mapping,
    *,
    run_id: str,
    project_id: int | None,
    item_refs: Any,
) -> list[str]:
    """Gate each open group once; answer the waiting reasons, empty when none waits."""
    if stage.get("scope") != "item":
        return []
    from yoke_core.domain.deployment_qa_plan_group_writes import group_subject

    stage_name = str(stage["name"])
    waiting: list[str] = []
    pending: list[PlanGroup] = []
    for group in run_groups(conn, run_id, stage_name):
        if not group.open:
            continue
        label = f"plan group {group.group_id} ({_plan_label(conn, group.plan_id)})"
        subject = group_subject(conn, run_id, stage_name, group, require_active=True)
        status = settle_group(conn, subject)
        if status.get("accepted"):
            continue
        reasons = list(status.get("reasons") or ())
        waiting.extend(f"{label}: {reason}" for reason in reasons)
        if project_id is None:
            continue
        if status.get("outcome") in FAILED_OUTCOMES:
            notify_plan_group_failure(
                conn, run_id=run_id, stage_name=stage_name, group=group,
                project_id=project_id, reasons=reasons, item_refs=item_refs,
            )
        else:
            pending.append(group)
    if pending and project_id is not None:
        notify_plan_groups_wait(
            conn, run_id=run_id, stage_name=stage_name, groups=pending,
            project_id=project_id, item_refs=item_refs,
        )
    return waiting


def plan_groups_wait_key(run_id: str, stage_name: str, groups: list[PlanGroup]) -> str:
    """One key per set of pending groups: a new group re-sends, the same set stays quiet."""
    digest = hashlib.sha256(
        ",".join(sorted(group.group_id for group in groups)).encode()
    ).hexdigest()[:16]
    return f"{PLAN_GROUPS_WAIT_PREFIX}{run_id}:{stage_name}:plan-groups:{digest}"


def _group_lines(conn, run_id, stage_name, groups, item_refs) -> list[str]:
    lines = []
    for group in groups:
        items = ", ".join(
            item_refs(member) for member in attaching_members(conn, run_id, group.plan_id)
        )
        lines.append(
            f"  yoke qa plan run --deployment-run-id {run_id} --stage {stage_name} "
            f"--plan {_plan_label(conn, group.plan_id)}   # group {group.group_id}; items {items or 'none'}"
        )
    return lines


def _deliver(conn, *, run_id, project_id, body, key, label) -> None:
    from yoke_core.domain.deployment_run_driver_notice import push_run_scoped_notice

    from yoke_core.domain.deployment_qa_stage_wake import route_phrase

    delivery = push_run_scoped_notice(
        conn,
        run_id=run_id,
        project_id=project_id,
        body_for_route=lambda route: f"Reaching {route_phrase(route)}. {body}",
        idempotency_key=key,
    )
    conn.commit()
    if not delivery:
        print(
            f"Run {run_id!r} {label} reached nobody: no live run driver, starting "
            "session or covering steering seat. Staff it manually."
        )


def notify_plan_groups_wait(
    conn, *, run_id, stage_name, groups, project_id, item_refs
) -> None:
    lines = _group_lines(conn, run_id, stage_name, groups, item_refs)
    body = (
        f"Deployment run {run_id} stage {stage_name!r} has {len(groups)} pending plan "
        "group(s). Each runs once for the whole release and answers every item that "
        "attaches its plan; no item holder runs it. Run each:\n"
        + "\n".join(lines)
        + f"\nThen re-drive the run with `yoke watch deploy -- {run_id}`. Check 'yoke deployment-runs get {run_id}'."
    )
    _deliver(
        conn, run_id=run_id, project_id=project_id, body=body,
        key=plan_groups_wait_key(run_id, stage_name, groups),
        label=f"stage {stage_name!r} plan groups",
    )


def notify_plan_group_failure(
    conn, *, run_id, stage_name, group, project_id, reasons, item_refs
) -> None:
    """One notice per failed verdict set of a group; never a member release."""
    lines = _group_lines(conn, run_id, stage_name, [group], item_refs)
    report = "; ".join(reasons) or "see the stage report"
    digest = hashlib.sha256(report.encode()).hexdigest()[:16]
    body = (
        f"Plan group {group.group_id} failed in deployment run {run_id} stage "
        f"{stage_name!r}: {report}. Its items are listed below. Decide who fixes "
        "what; a finding in one item is that item's to fix. A retry reruns only "
        "the failed cases:\n" + "\n".join(lines)
    )
    _deliver(
        conn, run_id=run_id, project_id=project_id, body=body,
        key=f"{PLAN_GROUP_FAILURE_PREFIX}{run_id}:{stage_name}:{group.group_id}:{digest}",
        label=f"plan group {group.group_id} failure",
    )


__all__ = [
    "PLAN_GROUPS_WAIT_PREFIX",
    "gate_plan_groups",
    "notify_plan_group_failure",
    "notify_plan_groups_wait",
    "plan_groups_wait_key",
    "plan_group_writer",
    "settle_group",
]
