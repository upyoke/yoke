"""Addressed-event fan-out and per-actor notification read state."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import (
    DECISION_RESOLVED,
    DEPLOYMENT_RUN_COMPLETED,
    IN_APP_NOTIFICATION_KINDS,
    ITEM_BLOCK_STATE_CHANGED,
    ITEM_BLOCKED_EVENT,
    ITEM_UNBLOCKED_EVENT,
    REQUEST_CREATED_EVENT,
    REQUEST_RESOLVED_EVENT,
    REQUEST_WITHDRAWN_EVENT,
)

_PRODUCER_NAMES = {
    DECISION_RESOLVED: (REQUEST_RESOLVED_EVENT,),
    DEPLOYMENT_RUN_COMPLETED: ("DeploymentRunSucceeded", "DeploymentRunFailed"),
    ITEM_BLOCK_STATE_CHANGED: (ITEM_BLOCKED_EVENT, ITEM_UNBLOCKED_EVENT),
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def addressed_actor_ids_for_event(
    conn: Any,
    *,
    event_name: str,
    notification_kind: str | None = None,
    event_context: Mapping[str, Any] | None = None,
) -> tuple[int, ...]:
    """Resolve one event's recipients from its transaction-owned context."""
    context = dict(event_context or {})

    if event_name in {REQUEST_CREATED_EVENT, REQUEST_WITHDRAWN_EVENT}:
        request_id = context.get("request_id")
        if request_id is None:
            raise ValueError(f"{event_name} needs request_id")
        from yoke_core.domain.decision_requests import (
            decision_request_authority_actor_ids,
        )

        return decision_request_authority_actor_ids(conn, int(request_id))

    recipients: set[int] = set()
    if notification_kind == DECISION_RESOLVED:
        if event_name != REQUEST_RESOLVED_EVENT:
            raise ValueError(
                f"{event_name!r} cannot produce {notification_kind!r} notifications"
            )
        request_id = context.get("request_id")
        if request_id is None:
            raise ValueError("decision resolution event needs request_id")
        p = _p(conn)
        row = conn.execute(
            f"SELECT originator_actor_id FROM decision_requests WHERE id = {p}",
            (int(request_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"decision request {request_id} does not exist")
        if row[0] is not None:
            recipients.add(int(row[0]))
    elif notification_kind == DEPLOYMENT_RUN_COMPLETED:
        if event_name not in _PRODUCER_NAMES[notification_kind]:
            raise ValueError(
                f"{event_name!r} cannot produce {notification_kind!r} notifications"
            )
        explicit_recipients = event_context is not None and (
            "initiator_actor_id" in event_context
            or "stage_approver_actor_ids" in event_context
        )
        run_id = str(context.get("run_id") or "")
        if run_id and not explicit_recipients:
            from yoke_core.domain.deployment_approval_requests import (
                deployment_completion_actor_ids,
            )

            recipients.update(deployment_completion_actor_ids(conn, run_id=run_id))
        else:
            initiator = context.get("initiator_actor_id")
            approvers = context.get("stage_approver_actor_ids") or []
            if initiator is not None:
                recipients.add(int(initiator))
            recipients.update(int(value) for value in approvers)
    elif notification_kind == ITEM_BLOCK_STATE_CHANGED:
        if event_name not in _PRODUCER_NAMES[notification_kind]:
            raise ValueError(
                f"{event_name!r} cannot produce {notification_kind!r} notifications"
            )
        owner = context.get("owner_actor_id")
        if owner is not None:
            recipients.add(int(owner))
    else:
        raise ValueError(f"unknown in-app notification kind {notification_kind!r}")
    return tuple(sorted(recipients))


def _event_actor_label(conn: Any, actor_id: int | None) -> str | None:
    if actor_id is None:
        return None
    p = _p(conn)
    row = conn.execute(
        "SELECT COALESCE(dl.label, a.system_component, "
        "'actor ' || CAST(a.id AS TEXT)) "
        "FROM actors a LEFT JOIN actor_labels dl "
        "ON dl.actor_id = a.id AND dl.surface = 'display' "
        f"WHERE a.id = {p}",
        (actor_id,),
    ).fetchone()
    return (
        str(row[0])
        if row is not None and row[0] is not None
        else f"actor {actor_id}"
    )


def fan_out_in_app_notification(
    conn: Any,
    *,
    event_envelope: Mapping[str, Any],
    project_id: int | None,
    notification_kind: str,
    recipient_actor_ids: Iterable[int],
    reason: str,
    created_at: str | None = None,
) -> int:
    """Materialize one idempotent notification snapshot per addressed actor."""
    if notification_kind not in IN_APP_NOTIFICATION_KINDS:
        raise ValueError(f"unknown in-app notification kind {notification_kind!r}")
    event_id = str(event_envelope.get("event_id") or "")
    event_name = str(event_envelope.get("event_name") or "")
    if not event_id or not event_name:
        raise ValueError("addressed event envelope needs event_id and event_name")
    event_created_at = str(created_at or event_envelope.get("created_at") or "")
    if not event_created_at:
        raise ValueError("addressed event envelope needs created_at")
    raw_actor_id = event_envelope.get("actor_id")
    event_actor_id = int(raw_actor_id) if raw_actor_id is not None else None
    event_actor_label = _event_actor_label(conn, event_actor_id)
    event_outcome = event_envelope.get("event_outcome")
    event_envelope_json = json.dumps(dict(event_envelope), ensure_ascii=False)
    p = _p(conn)
    if event_name not in _PRODUCER_NAMES[notification_kind]:
        raise ValueError(
            f"{event_name!r} cannot produce {notification_kind!r} notifications"
        )
    inserted = 0
    for actor_id in sorted({int(value) for value in recipient_actor_ids}):
        cursor = conn.execute(
            "INSERT INTO addressed_event_deliveries "
            "(channel, event_id, actor_id, notification_kind, reason, created_at, "
            "event_name, project_id, event_outcome, event_actor_id, "
            "event_actor_label, event_envelope) "
            f"VALUES ('in_app', {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, "
            f"{p}, {p}, {p}) "
            "ON CONFLICT(channel, event_id, actor_id) DO NOTHING",
            (
                event_id,
                actor_id,
                notification_kind,
                reason,
                event_created_at,
                event_name,
                project_id,
                event_outcome,
                event_actor_id,
                event_actor_label,
                event_envelope_json,
            ),
        )
        inserted += max(int(cursor.rowcount or 0), 0)
    return inserted


def dispatch_addressed_event(
    conn: Any,
    *,
    event_envelope: Mapping[str, Any],
    project_id: int | None,
    notification_kind: str,
    reason: str,
    created_at: str | None = None,
    event_context: Mapping[str, Any] | None = None,
) -> int:
    """Resolve and materialize in-app recipients without committing."""
    event_name = str(event_envelope.get("event_name") or "")
    stored_context = event_envelope.get("context")
    context = dict(stored_context) if isinstance(stored_context, Mapping) else {}
    if event_context:
        context.update(event_context)
    recipients = addressed_actor_ids_for_event(
        conn,
        event_name=event_name,
        notification_kind=notification_kind,
        event_context=context,
    )
    return fan_out_in_app_notification(
        conn,
        event_envelope=event_envelope,
        project_id=project_id,
        notification_kind=notification_kind,
        recipient_actor_ids=recipients,
        reason=reason,
        created_at=created_at,
    )


def notification_rows(
    conn: Any,
    actor_id: int,
    *,
    unread_only: bool = True,
) -> list[dict[str, Any]]:
    """Return addressed notification snapshots without reading telemetry."""
    p = _p(conn)
    unread = "AND d.read_at IS NULL " if unread_only else ""
    rows = conn.execute(
        "SELECT d.id, d.event_id, d.notification_kind, d.reason, "
        "d.read_at, d.created_at, d.event_name, d.project_id, "
        "d.event_outcome, d.event_actor_id, d.event_actor_label, "
        "d.event_envelope "
        "FROM addressed_event_deliveries d "
        f"WHERE d.actor_id = {p} AND d.channel = 'in_app' {unread}"
        "ORDER BY d.created_at DESC, d.id DESC",
        (actor_id,),
    ).fetchall()
    result = []
    for row in rows:
        value = _row_dict(row)
        envelope = value.pop("event_envelope", None)
        value.pop("event_actor_id", None)
        event_actor_label = value.pop("event_actor_label", None)
        try:
            value["event"] = json.loads(envelope) if envelope else {}
        except (TypeError, json.JSONDecodeError):
            value["event"] = {}
        if (
            value["event_name"] == REQUEST_RESOLVED_EVENT
            and event_actor_label
            and isinstance(value["event"], dict)
        ):
            context = value["event"].setdefault("context", {})
            if isinstance(context, dict):
                context.setdefault(
                    "resolution_actor_label",
                    str(event_actor_label),
                )
        result.append(value)
    return result


def mark_notification_read(
    conn: Any,
    actor_id: int,
    notification_id: int,
    read_at: str,
) -> bool:
    p = _p(conn)
    cursor = conn.execute(
        f"UPDATE addressed_event_deliveries SET read_at = {p} "
        f"WHERE id = {p} AND actor_id = {p} AND read_at IS NULL",
        (read_at, notification_id, actor_id),
    )
    return int(cursor.rowcount or 0) > 0


def mark_all_notifications_read(
    conn: Any,
    actor_id: int,
    read_at: str,
    *,
    project_ids: Iterable[int] | None = None,
) -> int:
    p = _p(conn)
    project_clause = ""
    params: list[Any] = [read_at, actor_id]
    if project_ids is not None:
        scoped_project_ids = sorted({int(value) for value in project_ids})
        if scoped_project_ids:
            placeholders = ", ".join(p for _ in scoped_project_ids)
            project_clause = (
                f" AND (project_id IS NULL OR project_id IN ({placeholders}))"
            )
            params.extend(scoped_project_ids)
        else:
            project_clause = " AND project_id IS NULL"
    cursor = conn.execute(
        f"UPDATE addressed_event_deliveries SET read_at = {p} "
        f"WHERE actor_id = {p} AND channel = 'in_app' AND read_at IS NULL"
        f"{project_clause}",
        tuple(params),
    )
    return max(int(cursor.rowcount or 0), 0)


__all__ = [
    "addressed_actor_ids_for_event",
    "dispatch_addressed_event",
    "fan_out_in_app_notification",
    "mark_all_notifications_read",
    "mark_notification_read",
    "notification_rows",
]
