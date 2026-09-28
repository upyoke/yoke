"""Settle carried items' own done approvals before shared run acceptance."""

from __future__ import annotations

from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.approval_policy import approval_policy_or_none
from yoke_core.domain.approval_gate import evaluate_lifecycle_approval
from yoke_core.domain.decision_request_subject_context import (
    item_posture_approval_source,
    workflow_default_approval_source,
)
from yoke_core.domain.decision_requests import list_subject_requests
from yoke_core.domain.lifecycle_approval_context import (
    lifecycle_transition_matches,
    load_lifecycle_item,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT i.id,i.status,i.project_sequence,p.slug,p.public_item_prefix "
        "FROM deployment_run_items dri JOIN items i ON i.id=dri.item_id "
        "JOIN projects p ON p.id=i.project_id "
        "WHERE dri.run_id=%s AND dri.delivery_intent='final' ORDER BY i.id",
        (run_id,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "status": str(row["status"]),
            "ref": format_item_ref(
                str(row["slug"]),
                str(row["public_item_prefix"] or ""),
                int(row["project_sequence"]),
            ),
        }
        for row in rows
    ]


def member_approval_blockers(
    conn: Any, run_id: str, *, create: bool = True
) -> list[str]:
    """Return named unresolved item decisions, creating each only once.

    The item's pinned workflow and project determine its approver. The run's
    project never substitutes for a bound member's own authority.
    """
    blockers: list[str] = []
    for member in _members(conn, run_id):
        item_id = member["id"]
        if member["status"] == "done":
            continue
        if member["status"] != "release":
            blockers.append(
                f"{member['ref']} is {member['status']}; restore its release "
                "wait before shared acceptance"
            )
            continue
        workflow = load_item_workflow_runtime(conn, item_id)
        policy = approval_policy_or_none(
            dict(workflow.policies.get("approval_defaults", {})).get("done"),
            path="policies.approval_defaults.done",
        )
        source = workflow_default_approval_source("done")
        if policy is None:
            from yoke_core.domain.dash_approval_posture import (
                approval_policy_for_transition,
            )

            policy = approval_policy_for_transition(
                conn, item_id=item_id, target_status="done"
            )
            source = item_posture_approval_source()
        if policy is None:
            continue
        history = list_subject_requests(conn, "item_transition", f"{item_id}:done")
        latest = history[0] if history else None
        matches = latest is not None and lifecycle_transition_matches(
            latest, load_lifecycle_item(conn, item_id), "done", source
        )
        if (
            matches
            and latest["status"] == "resolved"
            and latest["resolution_action"] == "reject"
        ):
            blockers.append(
                f"{member['ref']} decision request {latest['id']} was rejected; "
                "return the item to implementation and obtain approval for its correction"
            )
            continue
        if not create:
            if not (
                matches
                and latest["status"] == "resolved"
                and latest["resolution_action"] == "approve"
            ):
                blockers.append(
                    f"{member['ref']} decision request "
                    f"{latest['id'] if matches else 'missing'} is still required"
                )
            continue
        verdict = evaluate_lifecycle_approval(
            conn,
            item_id=item_id,
            to_stage_id="done",
            policy=policy,
            approval_source=source,
        )
        if not verdict.satisfied:
            blockers.append(
                f"{member['ref']} decision request {verdict.request_id} is "
                "awaiting its item's authorized approver in Inbox"
            )
    return blockers


def shared_approval_blocker(conn: Any, run_id: str) -> Any | None:
    """Return a stage verdict without opening its request while items wait."""
    blockers = member_approval_blockers(conn, run_id)
    if not blockers:
        return None
    from yoke_core.domain.approval_gate import ApprovalGateVerdict

    rejected = any("was rejected" in blocker for blocker in blockers)
    return ApprovalGateVerdict(
        False,
        0,
        "rejected_member" if rejected else "blocked_member",
        None,
        "; ".join(blockers),
    )


def run_qa_blockers(
    conn: Any, run_id: str, member_item_id: int | None, subject: dict[str, Any]
) -> list[str]:
    """Wait for carried decisions before opening a shared human QA request."""
    if (
        member_item_id is None
        and subject["stage"]["verdict"]["mode"] == "required_human"
    ):
        return member_approval_blockers(conn, run_id)
    return []


def resume_after_member_decision(conn: Any, item_id: int) -> None:
    """Revisit every live run carrying an answered item without an agent wake."""
    rows = conn.execute(
        "SELECT dr.id,dr.current_stage,df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        "JOIN deployment_run_items dri ON dri.run_id=dr.id "
        "WHERE dri.item_id=%s AND dri.delivery_intent='final' "
        "AND dr.status='executing' ORDER BY dr.id",
        (item_id,),
    ).fetchall()
    import json

    for row in rows:
        run_id = str(row["id"])
        if member_approval_blockers(conn, run_id, create=False):
            continue
        stage_name = str(row["current_stage"] or "")
        if stage_name == "complete":
            from yoke_core.domain.deployment_run_auto_completion import (
                continue_after_settlement,
            )

            continue_after_settlement(conn, run_id)
            continue
        stages = json.loads(str(row["stages"]))
        stage = next(
            (stage for stage in stages if stage.get("name") == stage_name), None
        )
        if stage is None:
            continue
        if stage.get("step_runner") == "qa" and stage.get("scope") == "run":
            from yoke_core.domain.deployment_qa_stage_settlement import settle_subject

            settle_subject(conn, run_id=run_id, stage=stage_name, member=None)
        elif stage.get("step_runner") == "human-approval":
            from yoke_core.domain.deployment_approval_requests import (
                evaluate_deployment_stage_approval,
            )

            evaluate_deployment_stage_approval(conn, run_id=run_id, stage=stage_name)


__all__ = [
    "member_approval_blockers",
    "resume_after_member_decision",
    "run_qa_blockers",
    "shared_approval_blocker",
]
