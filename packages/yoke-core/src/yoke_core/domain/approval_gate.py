"""Lifecycle approval gate backed by typed decision requests."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import json
from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_contract import REQUEST_WITHDRAWN_EVENT
from yoke_core.domain.decision_request_events import append_decision_event
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


@dataclass(frozen=True)
class ApprovalGateVerdict:
    satisfied: bool
    request_id: int
    request_status: str
    resolution_action: Optional[str]
    reason: str


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _item_context(conn: Any, item_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        "SELECT i.id, i.project_sequence, i.title, i.status, i.project_id, "
        "i.workflow_id, "
        "i.workflow_version_id, p.slug AS project, p.public_item_prefix, "
        "p.org_id "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    return {key: row[key] for key in row.keys()}


def role_authorities_for(
    *,
    project_id: int,
    org_id: Optional[int],
    role_names: Iterable[str],
) -> list[RoleAuthority]:
    result = []
    for role_name in sorted({str(value) for value in role_names}):
        if role_name == "admin":
            if org_id is None:
                raise ValueError("org admin approval needs the project's org")
            result.append(RoleAuthority("org", int(org_id), role_name))
        else:
            result.append(RoleAuthority("project", int(project_id), role_name))
    return result


def withdraw_stale_pending_request(
    conn: Any,
    request: dict[str, Any],
    *,
    session_id: str,
    reason: str,
) -> None:
    stamp = iso8601_now()
    p = _p(conn)
    conn.execute(
        "UPDATE decision_requests SET status='withdrawn', "
        f"withdrawal_reason={p}, withdrawn_at={p} "
        f"WHERE id={p} AND status='pending'",
        (reason, stamp, int(request["id"])),
    )
    append_decision_event(
        conn,
        REQUEST_WITHDRAWN_EVENT,
        actor_id=None,
        session_id=session_id,
        project_id=request.get("project_id"),
        org_id=request.get("org_id"),
        context={
            "request_id": int(request["id"]),
            "kind": str(request["kind"]),
            "reason": reason,
        },
        created_at=stamp,
    )


def verdict_from_request_history(
    conn: Any,
    history: list[dict[str, Any]],
    *,
    snapshot_matches: Callable[[dict[str, Any]], bool],
    session_id: str,
    stale_reason: str,
    reraise_after_reject: bool,
    waiting_reason: str,
    approved_reason: str,
    rejected_reason: str,
) -> Optional[ApprovalGateVerdict]:
    """Return a verdict from history, or None when a new request is required."""
    if not history:
        return None
    latest = history[0]
    matches = snapshot_matches(latest)
    status = str(latest.get("status") or "")
    action = latest.get("resolution_action")
    if status == "resolved" and action == "approve" and matches:
        return ApprovalGateVerdict(
            True,
            int(latest["id"]),
            "resolved",
            "approve",
            approved_reason,
        )
    if status == "pending" and matches:
        return ApprovalGateVerdict(
            False,
            int(latest["id"]),
            "pending",
            None,
            waiting_reason,
        )
    if status == "pending":
        withdraw_stale_pending_request(
            conn,
            latest,
            session_id=session_id,
            reason=stale_reason,
        )
        return None
    if (
        status == "resolved"
        and action == "reject"
        and matches
        and not reraise_after_reject
    ):
        return ApprovalGateVerdict(
            False,
            int(latest["id"]),
            "resolved",
            "reject",
            rejected_reason,
        )
    return None


def _matches_transition_snapshot(
    request: dict[str, Any],
    item: dict[str, Any],
    target: str,
) -> bool:
    context = request.get("subject_context")
    if not isinstance(context, dict):
        return False
    return (
        str(context.get("from_stage") or "") == str(item["status"])
        and str(context.get("transition") or "") == target
        and str(context.get("workflow_id") or "") == str(item["workflow_id"])
        and int(context.get("workflow_version_id") or 0)
        == int(item["workflow_version_id"])
        and request.get("consumed_at") is None
    )


@rollback_workflow_binding_write_errors
def evaluate_lifecycle_approval(
    conn: Any,
    *,
    item_id: int,
    to_stage_id: str,
    role_names: Iterable[str] = (),
    named_actor_ids: Iterable[int] = (),
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
) -> ApprovalGateVerdict:
    """Fail closed and create once until an authorized approval resolves."""
    target = to_stage_id.strip()
    if not target:
        raise ValueError("to_stage_id is required")
    lock_item_workflow_bindings(conn, (int(item_id),))
    item = _item_context(conn, int(item_id))
    subject_key = f"{int(item_id)}:{target}"
    waiting = "the transition is waiting for a human decision"
    verdict = verdict_from_request_history(
        conn,
        list_subject_requests(conn, "item_transition", subject_key),
        snapshot_matches=lambda request: _matches_transition_snapshot(
            request,
            item,
            target,
        ),
        session_id=session_id,
        stale_reason="transition source or pinned workflow changed",
        reraise_after_reject=True,
        waiting_reason=waiting,
        approved_reason="the declared approval was resolved",
        rejected_reason="the transition was rejected",
    )
    if verdict is not None:
        conn.commit()
        return verdict

    public_ref = format_item_ref(
        str(item["project"]),
        str(item["public_item_prefix"] or ""),
        int(item["project_sequence"]),
    )
    request, _ = create_decision_request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key=subject_key,
        project_id=int(item["project_id"]),
        originator_actor_id=originator_actor_id,
        role_authorities=role_authorities_for(
            project_id=int(item["project_id"]),
            org_id=item["org_id"],
            role_names=role_names,
        ),
        named_actor_ids=named_actor_ids,
        subject_context={
            "item_id": int(item_id),
            "public_ref": public_ref,
            "title": f"{public_ref} — approve the {target} transition",
            "item_title": str(item["title"]),
            "from_stage": str(item["status"]),
            "transition": target,
            "workflow_id": str(item["workflow_id"]),
            "workflow_version_id": int(item["workflow_version_id"]),
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


@rollback_workflow_binding_write_errors
def consume_lifecycle_approval(
    conn: Any,
    *,
    request_id: int,
    item_id: int,
    from_stage_id: str,
    to_stage_id: str,
    workflow_version_id: int,
    commit: bool = True,
) -> None:
    """Consume one resolved approval with its successful transition."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    p = _p(conn)
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        "SELECT status, resolution_action, subject_context, consumed_at "
        f"FROM decision_requests WHERE id={p}{suffix}",
        (int(request_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"decision request {request_id} does not exist")
    values = (
        dict(row)
        if hasattr(row, "keys")
        else {
            "status": row[0],
            "resolution_action": row[1],
            "subject_context": row[2],
            "consumed_at": row[3],
        }
    )
    try:
        context = json.loads(str(values["subject_context"] or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"decision request {request_id} has invalid subject context"
        ) from exc
    expected = {
        "item_id": int(item_id),
        "from_stage": str(from_stage_id),
        "transition": str(to_stage_id),
        "workflow_version_id": int(workflow_version_id),
    }
    actual = {
        "item_id": int(context.get("item_id") or 0),
        "from_stage": str(context.get("from_stage") or ""),
        "transition": str(context.get("transition") or ""),
        "workflow_version_id": int(context.get("workflow_version_id") or 0),
    }
    if (
        str(values["status"]) != "resolved"
        or str(values["resolution_action"]) != "approve"
        or values["consumed_at"] is not None
        or actual != expected
    ):
        raise ValueError(
            f"decision request {request_id} is not an unconsumed approval "
            "for this transition snapshot"
        )
    stamp = iso8601_now()
    cursor = conn.execute(
        "UPDATE decision_requests SET consumed_at={p}, "
        "consumed_from_stage={p}, consumed_to_stage={p}, "
        "consumed_workflow_version_id={p} "
        f"WHERE id={p} AND consumed_at IS NULL".format(p=p),
        (
            stamp,
            str(from_stage_id),
            str(to_stage_id),
            int(workflow_version_id),
            int(request_id),
        ),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ValueError(f"decision request {request_id} was already consumed")
    if commit:
        conn.commit()


__all__ = [
    "ApprovalGateVerdict",
    "consume_lifecycle_approval",
    "evaluate_lifecycle_approval",
    "role_authorities_for",
    "verdict_from_request_history",
    "withdraw_stale_pending_request",
]
