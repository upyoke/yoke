"""Recorded human decisions, and the resolution a request derives from them.

A decision request is one question; the people it addresses answer it one
decision at a time. Each answer lands as its own row -- who decided, what they
chose, why, and when -- and the request's resolution is DERIVED from those rows
against the policy the request was created with, never written by whoever
happened to answer first.

That derivation is the whole difference between the two modes. Under ``any``
the first approval settles the question, which is why one decision and one
resolver used to be the same thing. Under ``all`` every checked box needs its
own decision, so a request can hold an answer and still be pending, and the
person who already answered needs to see their part is done rather than an
action they cannot take twice.

A rejection is never partial: the first rejecting answer from anyone the policy
addresses resolves the request against, whatever else is outstanding.

Role membership is read live, here, at evaluation -- never snapshotted onto the
request -- so a role box is satisfied by a decision from whoever holds that role
now, and an approver who has since lost the role no longer stands in for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.approval_policy import (
    APPROVAL_MODE_ALL,
    APPROVAL_ROLE_LABELS,
    DEFAULT_APPROVAL_MODE,
)

#: Answers that settle a request against its subject on their own.
REJECTING_ACTIONS = frozenset({"reject", "deny"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class ApprovalProgress:
    """How far one request has got toward the resolution its policy needs."""

    mode: str
    required: int
    satisfied: int
    outstanding: tuple[str, ...]
    decided_actor_ids: tuple[int, ...]
    resolved: bool
    action: Optional[str] = None
    deciding_actor_id: Optional[int] = None
    note: Optional[str] = None

    @property
    def summary(self) -> str:
        if self.resolved:
            return f"Resolved as {self.action}."
        waiting = ", ".join(self.outstanding) or "no one"
        if self.mode == APPROVAL_MODE_ALL:
            return (
                f"{self.satisfied} of {self.required} decisions recorded · "
                f"waiting on {waiting}"
            )
        return f"Waiting on {waiting}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "required": self.required,
            "satisfied": self.satisfied,
            "outstanding": list(self.outstanding),
            "decided_actor_ids": list(self.decided_actor_ids),
            "resolved": self.resolved,
            "action": self.action,
            "summary": self.summary,
        }


def list_decisions(conn: Any, request_id: int) -> list[dict[str, Any]]:
    """Return one request's answers in the order they were given."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT id, actor_id, action, note, decided_at "
        f"FROM decision_request_decisions WHERE request_id = {p} "
        "ORDER BY decided_at, id",
        (int(request_id),),
    ).fetchall()
    return [
        {
            "id": int(row[0]),
            "actor_id": int(row[1]),
            "action": str(row[2]),
            "note": row[3],
            "decided_at": str(row[4]),
        }
        for row in rows
    ]


def actor_decision(
    conn: Any,
    request_id: int,
    actor_id: int,
) -> Optional[dict[str, Any]]:
    """Return this actor's own answer, when they have already given one."""
    for decision in list_decisions(conn, request_id):
        if decision["actor_id"] == int(actor_id):
            return decision
    return None


def record_decision(
    conn: Any,
    *,
    request_id: int,
    actor_id: int,
    action: str,
    note: Optional[str],
    decided_at: str,
) -> dict[str, Any]:
    """Record one person's answer, refusing a second answer from the same one."""
    existing = actor_decision(conn, request_id, actor_id)
    if existing is not None:
        raise ValueError(
            f"actor {actor_id} already decided request {request_id}: "
            f"{existing['action']} at {existing['decided_at']}. "
            "A decision is final; withdraw the request to ask again."
        )
    p = _p(conn)
    conn.execute(
        "INSERT INTO decision_request_decisions "
        f"(request_id, actor_id, action, note, decided_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (int(request_id), int(actor_id), str(action), note, str(decided_at)),
    )
    recorded = actor_decision(conn, request_id, actor_id)
    if recorded is None:
        raise RuntimeError(
            f"decision by actor {actor_id} on request {request_id} did not persist"
        )
    return recorded


def actor_display_label(conn: Any, actor_id: int) -> str:
    """Name one approver the way the person reading the Inbox knows them."""
    row = conn.execute(
        "SELECT label FROM actor_labels "
        f"WHERE actor_id = {_p(conn)} AND surface = 'display'",
        (int(actor_id),),
    ).fetchone()
    label = str(row[0]).strip() if row is not None and row[0] else ""
    return label or f"actor {int(actor_id)}"


def _holds_role(
    conn: Any,
    *,
    actor_id: int,
    scope_kind: str,
    scope_id: int,
    role_name: str,
) -> bool:
    table = "actor_org_roles" if scope_kind == "org" else "actor_project_roles"
    scope_column = "org_id" if scope_kind == "org" else "project_id"
    p = _p(conn)
    return (
        conn.execute(
            f"SELECT 1 FROM {table} ar JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.actor_id = {p} AND ar.{scope_column} = {p} "
            f"AND r.name = {p} LIMIT 1",
            (int(actor_id), int(scope_id), str(role_name)),
        ).fetchone()
        is not None
    )


def _boxes(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the checked boxes the request's policy addressed."""
    boxes: list[dict[str, Any]] = []
    for authority in request.get("role_authorities") or []:
        role_name = str(authority["role_name"])
        boxes.append(
            {
                "kind": "role",
                "scope_kind": str(authority["scope_kind"]),
                "scope_id": int(authority["scope_id"]),
                "role_name": role_name,
                "label": APPROVAL_ROLE_LABELS.get(role_name, role_name),
            }
        )
    for actor_id in request.get("named_actor_ids") or []:
        boxes.append(
            {"kind": "actor", "actor_id": int(actor_id), "label": None}
        )
    return boxes


def _box_satisfied(
    conn: Any,
    box: dict[str, Any],
    decided_actor_ids: list[int],
) -> bool:
    if box["kind"] == "actor":
        return int(box["actor_id"]) in decided_actor_ids
    return any(
        _holds_role(
            conn,
            actor_id=actor_id,
            scope_kind=box["scope_kind"],
            scope_id=box["scope_id"],
            role_name=box["role_name"],
        )
        for actor_id in decided_actor_ids
    )


def _box_label(conn: Any, box: dict[str, Any]) -> str:
    if box["kind"] == "actor":
        return actor_display_label(conn, int(box["actor_id"]))
    return str(box["label"])


def evaluate_decisions(conn: Any, request: dict[str, Any]) -> ApprovalProgress:
    """Derive one request's resolution from its answers against its policy."""
    mode = str(request.get("approval_mode") or DEFAULT_APPROVAL_MODE)
    boxes = _boxes(request)
    decisions = list_decisions(conn, int(request["id"]))
    required = len(boxes) if mode == APPROVAL_MODE_ALL else min(len(boxes), 1)
    decided_actor_ids = [decision["actor_id"] for decision in decisions]

    def _satisfied(through: list[dict[str, Any]]) -> int:
        actor_ids = [decision["actor_id"] for decision in through]
        count = sum(1 for box in boxes if _box_satisfied(conn, box, actor_ids))
        return count if mode == APPROVAL_MODE_ALL else min(count, 1)

    for index, decision in enumerate(decisions):
        through = decisions[: index + 1]
        rejecting = decision["action"] in REJECTING_ACTIONS
        if rejecting or (required and _satisfied(through) >= required):
            return ApprovalProgress(
                mode=mode,
                required=required,
                satisfied=required,
                outstanding=(),
                decided_actor_ids=tuple(decided_actor_ids),
                resolved=True,
                action=str(decision["action"]),
                deciding_actor_id=int(decision["actor_id"]),
                note=decision["note"],
            )
    outstanding = tuple(
        _box_label(conn, box)
        for box in boxes
        if not _box_satisfied(conn, box, decided_actor_ids)
    )
    return ApprovalProgress(
        mode=mode,
        required=required,
        satisfied=_satisfied(decisions),
        outstanding=outstanding,
        decided_actor_ids=tuple(decided_actor_ids),
        resolved=False,
    )


__all__ = [
    "ApprovalProgress",
    "REJECTING_ACTIONS",
    "actor_decision",
    "actor_display_label",
    "evaluate_decisions",
    "list_decisions",
    "record_decision",
]
