"""Lifecycle approval gate backed by typed decision requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
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
        "SELECT i.id, i.title, i.status, i.project_id, i.workflow_id, "
        "i.workflow_version_id, p.slug AS project, p.public_item_prefix, "
        "p.org_id "
        "FROM items i JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    return {key: row[key] for key in row.keys()}


def _role_authorities(
    item: dict[str, Any], role_names: Iterable[str],
) -> list[RoleAuthority]:
    result = []
    for role_name in sorted({str(value) for value in role_names}):
        if role_name == "admin":
            if item["org_id"] is None:
                raise ValueError("org admin approval needs the project's org")
            result.append(RoleAuthority("org", int(item["org_id"]), role_name))
        else:
            result.append(
                RoleAuthority("project", int(item["project_id"]), role_name)
            )
    return result


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
    item = _item_context(conn, int(item_id))
    subject_key = f"{int(item_id)}:{target}"
    history = list_subject_requests(conn, "item_transition", subject_key)
    if history:
        latest = history[0]
        if (
            latest["status"] == "resolved"
            and latest["resolution_action"] == "approve"
        ):
            return ApprovalGateVerdict(
                True, int(latest["id"]), "resolved", "approve",
                "the declared approval was resolved",
            )
        if latest["status"] == "pending":
            return ApprovalGateVerdict(
                False, int(latest["id"]), "pending", None,
                "the transition is waiting for a human decision",
            )

    prefix = str(item["public_item_prefix"] or "YOK")
    request, _ = create_decision_request(
        conn,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key=subject_key,
        project_id=int(item["project_id"]),
        originator_actor_id=originator_actor_id,
        role_authorities=_role_authorities(item, role_names),
        named_actor_ids=named_actor_ids,
        subject_context={
            "item_id": int(item_id),
            "item_ref": f"{prefix}-{int(item_id)}",
            "title": (
                f"{prefix}-{int(item_id)} — approve the {target} transition"
            ),
            "item_title": str(item["title"]),
            "from_stage": str(item["status"]),
            "transition": target,
            "workflow_id": str(item["workflow_id"]),
            "workflow_version_id": int(item["workflow_version_id"]),
        },
        session_id=session_id,
    )
    return ApprovalGateVerdict(
        False, int(request["id"]), "pending", None,
        "the transition is waiting for a human decision",
    )


__all__ = ["ApprovalGateVerdict", "evaluate_lifecycle_approval"]
