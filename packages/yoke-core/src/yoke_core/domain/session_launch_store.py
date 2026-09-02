"""SQL persistence helpers for the session-launch state machine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.sender_surface import (
    HARNESS_SESSION_SENDER_SURFACE,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_types import LaunchRecord, SessionLaunchError


LAUNCH_COLUMNS = (
    "launch_id, requester_actor_id, requester_session_id, project_id, "
    "requested_surface, selected_surface, requested_machine_id, requested_model, "
    "presentation_preference, session_name, allow_surface_fallback, message_id, "
    "idempotency_key, state, assigned_relay_id, assigned_machine_id, "
    "native_session_id, attestation_hash, attestation_consumed_at, "
    "registered_session_id, deadline_at, created_at, assigned_at, launching_at, "
    "awaiting_registration_at, completed_at, result_code, result_evidence, origin, "
    "native_launch_pid, native_launch_phase, native_launch_observed_at, "
    "spawn_duration_ms"
)
_MUTABLE_LAUNCH_COLUMNS = frozenset(
    {
        "state",
        "selected_surface",
        "assigned_relay_id",
        "assigned_machine_id",
        "native_session_id",
        "attestation_hash",
        "attestation_consumed_at",
        "registered_session_id",
        "deadline_at",
        "assigned_at",
        "launching_at",
        "awaiting_registration_at",
        "completed_at",
        "result_code",
        "result_evidence",
        "native_launch_pid",
        "native_launch_phase",
        "native_launch_observed_at",
        "spawn_duration_ms",
    }
)


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def value(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return row[index]


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def add_seconds(raw: str, seconds: int) -> str:
    value = parse_time(raw) + timedelta(seconds=seconds)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def attestation_digest(value: str) -> str:
    return f"sha256:{sha256_text(value)}"


def bootstrap_prompt(launch_id: str) -> str:
    return native_launch_bootstrap(launch_id)


def begin_mutation(conn: Any) -> None:
    if db_backend.connection_is_postgres(conn):
        return
    if not bool(getattr(conn, "in_transaction", False)):
        conn.execute("BEGIN IMMEDIATE")


def row_to_launch(row: Any) -> LaunchRecord:
    return LaunchRecord(
        launch_id=str(value(row, "launch_id", 0)),
        requester_actor_id=int(value(row, "requester_actor_id", 1)),
        requester_session_id=value(row, "requester_session_id", 2),
        project_id=int(value(row, "project_id", 3)),
        requested_surface=str(value(row, "requested_surface", 4)),
        selected_surface=str(value(row, "selected_surface", 5)),
        requested_machine_id=value(row, "requested_machine_id", 6),
        requested_model=value(row, "requested_model", 7),
        presentation_preference=value(row, "presentation_preference", 8),
        session_name=value(row, "session_name", 9),
        allow_surface_fallback=bool(value(row, "allow_surface_fallback", 10)),
        message_id=str(value(row, "message_id", 11)),
        idempotency_key=value(row, "idempotency_key", 12),
        state=str(value(row, "state", 13)),
        assigned_relay_id=value(row, "assigned_relay_id", 14),
        assigned_machine_id=value(row, "assigned_machine_id", 15),
        native_session_id=value(row, "native_session_id", 16),
        attestation_hash=value(row, "attestation_hash", 17),
        attestation_consumed_at=value(row, "attestation_consumed_at", 18),
        registered_session_id=value(row, "registered_session_id", 19),
        deadline_at=str(value(row, "deadline_at", 20)),
        created_at=str(value(row, "created_at", 21)),
        assigned_at=value(row, "assigned_at", 22),
        launching_at=value(row, "launching_at", 23),
        awaiting_registration_at=value(row, "awaiting_registration_at", 24),
        completed_at=value(row, "completed_at", 25),
        result_code=value(row, "result_code", 26),
        result_evidence=value(row, "result_evidence", 27),
        origin=str(value(row, "origin", 28)),
        native_launch_pid=value(row, "native_launch_pid", 29),
        native_launch_phase=value(row, "native_launch_phase", 30),
        native_launch_observed_at=value(row, "native_launch_observed_at", 31),
        spawn_duration_ms=value(row, "spawn_duration_ms", 32),
    )


def get_launch(conn: Any, launch_id: str, *, for_update: bool = False) -> LaunchRecord:
    suffix = (
        " FOR UPDATE" if for_update and db_backend.connection_is_postgres(conn) else ""
    )
    p = marker(conn)
    row = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches WHERE launch_id = {p}{suffix}",
        (launch_id,),
    ).fetchone()
    if row is None:
        raise SessionLaunchError("not_found", f"launch {launch_id!r} not found")
    return row_to_launch(row)


def get_launch_by_dedupe(
    conn: Any,
    actor_id: int,
    idempotency_key: str,
) -> LaunchRecord | None:
    p = marker(conn)
    row = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches "
        f"WHERE requester_actor_id = {p} AND idempotency_key = {p}",
        (actor_id, idempotency_key),
    ).fetchone()
    return row_to_launch(row) if row is not None else None


def list_launches(
    conn: Any,
    *,
    project_id: int | None = None,
    state: str | None = None,
    limit: int = 50,
) -> list[LaunchRecord]:
    p = marker(conn)
    where: list[str] = []
    params: list[Any] = []
    if project_id is not None:
        where.append(f"project_id = {p}")
        params.append(project_id)
    if state:
        where.append(f"state = {p}")
        params.append(state)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    params.append(max(1, min(int(limit), 500)))
    rows = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches{clause} "
        f"ORDER BY created_at DESC, launch_id DESC LIMIT {p}",
        tuple(params),
    ).fetchall()
    return [row_to_launch(row) for row in rows]


def update_launch(
    conn: Any,
    launch_id: str,
    *,
    delivery_changed_at: str | None = None,
    **changes: Any,
) -> LaunchRecord:
    unknown = set(changes) - _MUTABLE_LAUNCH_COLUMNS
    if unknown:
        raise ValueError(f"unknown launch update columns: {sorted(unknown)}")
    if not changes:
        return get_launch(conn, launch_id)
    p = marker(conn)
    assignments = ", ".join(f"{name} = {p}" for name in changes)
    conn.execute(
        f"UPDATE session_launches SET {assignments} WHERE launch_id = {p}",
        (*changes.values(), launch_id),
    )
    next_state = changes.get("state")
    if next_state:
        from yoke_core.domain.session_launch_delivery_state import (
            TERMINAL_DELIVERY_STATES,
            close_launch_delivery,
            reopen_launch_delivery,
        )

        if next_state in TERMINAL_DELIVERY_STATES:
            close_launch_delivery(
                conn,
                launch_id=launch_id,
                state=str(next_state),
                changed_at=str(
                    delivery_changed_at or changes.get("completed_at") or utc_now()
                ),
            )
        elif next_state in {"assigned", "launching", "awaiting_registration"}:
            reopen_launch_delivery(conn, launch_id=launch_id)
    return get_launch(conn, launch_id)


def insert_instruction_message(
    conn: Any,
    *,
    message_id: str,
    launch_id: str,
    actor_id: int,
    session_id: str | None,
    sender_surface: str | None,
    project_id: int,
    body: str,
    created_at: str,
    expires_at: str,
) -> None:
    p = marker(conn)
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, idempotency_key, created_at, expires_at, sender_surface) "
        f"VALUES ({', '.join(p for _ in range(10))})",
        (
            message_id,
            actor_id,
            session_id,
            body,
            sha256_text(body),
            canonical_json(
                {"anchor": "launch", "launch_id": launch_id, "project_id": project_id}
            ),
            None,
            created_at,
            expires_at,
            sender_surface or (HARNESS_SESSION_SENDER_SURFACE if session_id else None),
        ),
    )


def instruction_message(conn: Any, message_id: str) -> tuple[str, str, int]:
    p = marker(conn)
    row = conn.execute(
        "SELECT body, body_sha256, sender_actor_id FROM session_messages "
        f"WHERE message_id = {p}",
        (message_id,),
    ).fetchone()
    if row is None:
        raise SessionLaunchError("instruction_missing", "launch instruction is missing")
    return (
        str(value(row, "body", 0)),
        str(value(row, "body_sha256", 1)),
        int(value(row, "sender_actor_id", 2)),
    )


def delete_message(conn: Any, message_id: str) -> None:
    p = marker(conn)
    conn.execute(f"DELETE FROM session_messages WHERE message_id = {p}", (message_id,))


def next_attempt_number(conn: Any, launch_id: str) -> int:
    p = marker(conn)
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_number), 0) FROM session_launch_attempts "
        f"WHERE launch_id = {p}",
        (launch_id,),
    ).fetchone()
    return int(value(row, "max", 0) or 0) + 1


def rows_to_dicts(rows: Iterable[LaunchRecord]) -> list[dict[str, Any]]:
    return [row.to_dict() for row in rows]


__all__ = [
    "LAUNCH_COLUMNS",
    "add_seconds",
    "attestation_digest",
    "begin_mutation",
    "bootstrap_prompt",
    "canonical_json",
    "delete_message",
    "get_launch",
    "get_launch_by_dedupe",
    "insert_instruction_message",
    "instruction_message",
    "list_launches",
    "marker",
    "next_attempt_number",
    "parse_time",
    "rows_to_dicts",
    "sha256_text",
    "update_launch",
    "utc_now",
    "value",
]
