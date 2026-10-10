"""SQL persistence helpers for the session-launch state machine."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from typing import Any, Iterable

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_contracts.session_control.sender_surface import (
    HARNESS_SESSION_SENDER_SURFACE,
)
from yoke_contracts.timestamps import parse_instant
from yoke_contracts.timestamps import utc_now as utc_now
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain import db_backend
from yoke_core.domain.session_launch_types import LaunchRecord, SessionLaunchError


from yoke_core.domain.session_launch_columns import (
    LAUNCH_COLUMNS as LAUNCH_COLUMNS,
    MUTABLE_LAUNCH_COLUMNS,
    INSTANT_LAUNCH_COLUMNS,
)


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def value(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError):
        return row[index]


def canonical_json(payload: Any) -> str:
    return dumps_compact(payload)


def parse_time(raw: datetime | str) -> datetime:
    return parse_instant(raw)


def add_seconds(raw: datetime | str, seconds: int) -> datetime:
    return parse_instant(raw) + timedelta(seconds=seconds)


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
        requested_reasoning_effort=value(row, "requested_reasoning_effort", 8),
        requested_context_window_tokens=value(
            row, "requested_context_window_tokens", 9
        ),
        presentation_preference=value(row, "presentation_preference", 10),
        session_name=value(row, "session_name", 11),
        allow_surface_fallback=bool(value(row, "allow_surface_fallback", 12)),
        message_id=str(value(row, "message_id", 13)),
        idempotency_key=value(row, "idempotency_key", 14),
        state=str(value(row, "state", 15)),
        assigned_relay_id=value(row, "assigned_relay_id", 16),
        assigned_machine_id=value(row, "assigned_machine_id", 17),
        native_session_id=value(row, "native_session_id", 18),
        attestation_hash=value(row, "attestation_hash", 19),
        attestation_consumed_at=None
        if value(row, "attestation_consumed_at", 20) is None
        else parse_instant(value(row, "attestation_consumed_at", 20)),
        registered_session_id=value(row, "registered_session_id", 21),
        deadline_at=parse_instant(value(row, "deadline_at", 22)),
        created_at=parse_instant(value(row, "created_at", 23)),
        assigned_at=None
        if value(row, "assigned_at", 24) is None
        else parse_instant(value(row, "assigned_at", 24)),
        launching_at=None
        if value(row, "launching_at", 25) is None
        else parse_instant(value(row, "launching_at", 25)),
        awaiting_registration_at=None
        if value(row, "awaiting_registration_at", 26) is None
        else parse_instant(value(row, "awaiting_registration_at", 26)),
        completed_at=None
        if value(row, "completed_at", 27) is None
        else parse_instant(value(row, "completed_at", 27)),
        result_code=value(row, "result_code", 28),
        result_evidence=value(row, "result_evidence", 29),
        origin=str(value(row, "origin", 30)),
        native_launch_pid=value(row, "native_launch_pid", 31),
        native_launch_phase=value(row, "native_launch_phase", 32),
        native_launch_observed_at=None
        if value(row, "native_launch_observed_at", 33) is None
        else parse_instant(value(row, "native_launch_observed_at", 33)),
        spawn_duration_ms=value(row, "spawn_duration_ms", 34),
        spawn_hold_reason=value(row, "spawn_hold_reason", 35),
        placement_reason=value(row, "placement_reason", 36),
        resolved_model=value(row, "resolved_model", 37),
        resolved_reasoning_effort=value(row, "resolved_reasoning_effort", 38),
        resolved_context_window_tokens=value(row, "resolved_context_window_tokens", 39),
        requested_level=value(row, "requested_level", 40),
        level_placement=value(row, "level_placement", 41),
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


def update_launch(
    conn: Any,
    launch_id: str,
    *,
    delivery_changed_at: datetime | str | None = None,
    **changes: Any,
) -> LaunchRecord:
    if delivery_changed_at is not None:
        delivery_changed_at = parse_instant(delivery_changed_at)
    unknown = set(changes) - MUTABLE_LAUNCH_COLUMNS
    if unknown:
        raise ValueError(f"unknown launch update columns: {sorted(unknown)}")
    if not changes:
        return get_launch(conn, launch_id)
    p = marker(conn)
    assignments = ", ".join(f"{name} = {p}" for name in changes)
    conn.execute(
        f"UPDATE session_launches SET {assignments} WHERE launch_id = {p}",
        (
            *(
                instant_parameter(conn, None if val is None else parse_instant(val))
                if name in INSTANT_LAUNCH_COLUMNS
                else val
                for name, val in changes.items()
            ),
            launch_id,
        ),
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
                changed_at=(
                    delivery_changed_at
                    if delivery_changed_at is not None
                    else changes["completed_at"]
                    if changes.get("completed_at") is not None
                    else utc_now()
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
    created_at: datetime,
    expires_at: datetime,
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
            instant_parameter(conn, parse_instant(created_at)),
            instant_parameter(conn, parse_instant(expires_at)),
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
    "marker",
    "next_attempt_number",
    "parse_time",
    "rows_to_dicts",
    "sha256_text",
    "update_launch",
    "utc_now",
    "value",
]
