"""Bind launch delivery to an exact session already in the fleet registry."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_binding_evidence import (
    bound_registration_evidence,
)
from yoke_core.domain.session_launch_model_stamp import (
    stamp_launch_requested_facts,
)
from yoke_core.domain.session_launch_registration_grace import (
    hold_launch_registration_grace,
)
from yoke_core.domain.session_launch_store import (
    canonical_json,
    marker,
    update_launch,
    value,
)
from yoke_core.domain.session_launch_types import LaunchRecord, SessionLaunchError
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.sessions_analytics import SessionError


def registered_session_facts(conn: Any, session_id: str) -> dict[str, Any] | None:
    """Return the identity facts needed for an exact launch binding."""
    p = marker(conn)
    row = conn.execute(
        "SELECT project_id, executor_surface, executor_version, machine_id, "
        f"model, ended_at FROM harness_sessions WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "project_id": int(value(row, "project_id", 0)),
        "surface": value(row, "executor_surface", 1),
        "version": value(row, "executor_version", 2),
        "machine_id": value(row, "machine_id", 3),
        "model": value(row, "model", 4),
        "ended_at": value(row, "ended_at", 5),
    }


def require_registered_session_facts(conn: Any, session_id: str) -> dict[str, Any]:
    facts = registered_session_facts(conn, session_id)
    if facts is None:
        raise SessionLaunchError(
            "session_not_registered",
            "launch binding requires a registered session",
        )
    return facts


def _require_launch_session_context(
    launch: LaunchRecord, facts: dict[str, Any]
) -> None:
    if facts["project_id"] != launch.project_id:
        raise SessionLaunchError("project_mismatch", "registered project differs")
    if facts["surface"] != launch.selected_surface:
        raise SessionLaunchError("surface_mismatch", "registered surface differs")
    if launch.assigned_machine_id and facts["machine_id"] != launch.assigned_machine_id:
        raise SessionLaunchError("machine_mismatch", "registered machine differs")


def require_exact_launch_session(
    launch: LaunchRecord, session_id: str, facts: dict[str, Any]
) -> None:
    _require_launch_session_context(launch, facts)
    if launch.native_session_id != session_id:
        raise SessionLaunchError(
            "native_session_mismatch",
            "registered session does not equal the native binding id",
        )


def adopt_attested_session_identity(
    conn: Any,
    *,
    launch: LaunchRecord,
    session_id: str,
    facts: dict[str, Any],
    now: str,
) -> LaunchRecord:
    """Recover a missing native id from a validated launch attestation."""
    if (
        launch.state != "outcome_unknown"
        or launch.native_session_id
        or launch.registered_session_id
    ):
        raise SessionLaunchError(
            "invalid_state",
            "launch cannot adopt an attested session identity",
        )
    _require_launch_session_context(launch, facts)
    p = marker(conn)
    stamped = conn.execute(
        "UPDATE session_launch_attempts SET native_session_id="
        + p
        + " WHERE native_session_id IS NULL AND attempt_id=("
        "SELECT attempt_id FROM session_launch_attempts WHERE launch_id="
        + p
        + " ORDER BY attempt_number DESC LIMIT 1)",
        (session_id, launch.launch_id),
    )
    if stamped.rowcount != 1:
        raise SessionLaunchError(
            "attempt_identity_conflict",
            "latest launch attempt cannot adopt the attested session identity",
        )
    return update_launch(
        conn,
        launch.launch_id,
        state="awaiting_registration",
        native_session_id=session_id,
        awaiting_registration_at=now,
        completed_at=None,
        result_code="native_identity_attested",
    )


def _extend_message_expiry(conn: Any, *, message_id: str, expires_at: str) -> None:
    """Realign the instruction message TTL to the launch's live deadline.

    A retried launch resets its own ``deadline_at`` but leaves the instruction
    message pinned to the deadline it was created under, so a recipient
    inserted here is swept to ``expired`` within a second and the mandate is
    never delivered. Binding is where the delivery target becomes real, so it
    is also where the message TTL is realigned to the deadline the recipient
    will actually live under. Only ever extend, never shorten.
    """
    p = marker(conn)
    conn.execute(
        f"UPDATE session_messages SET expires_at={p} "
        f"WHERE message_id={p} AND expires_at < {p}",
        (expires_at, message_id, expires_at),
    )


def _insert_pending_recipient(
    conn: Any,
    *,
    launch: LaunchRecord,
    session_id: str,
    facts: dict[str, Any],
    now: str,
    wake_after: str,
) -> None:
    p = marker(conn)
    resolution = canonical_json({"anchor": "launch", "launch_id": launch.launch_id})
    routing = canonical_json(
        {
            "relay_id": launch.assigned_relay_id,
            "machine_id": launch.assigned_machine_id,
            "surface": launch.selected_surface,
        }
    )
    values = (
        launch.message_id,
        session_id,
        launch.project_id,
        resolution,
        routing,
        facts["surface"],
        facts["version"],
        facts["machine_id"],
        "pending",
        now,
        wake_after,
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, routing_snapshot, "
        "executor_surface, executor_version, machine_id, state, created_at, wake_after) "
        f"VALUES ({', '.join(p for _ in values)}) "
        "ON CONFLICT(message_id, session_id) DO UPDATE SET "
        "project_id=excluded.project_id, resolution_evidence=excluded.resolution_evidence, "
        "routing_snapshot=excluded.routing_snapshot, "
        "executor_surface=excluded.executor_surface, "
        "executor_version=excluded.executor_version, machine_id=excluded.machine_id, "
        "state='pending', created_at=excluded.created_at, wake_after=excluded.wake_after, "
        "injection_lease_id=NULL, injection_leased_at=NULL, "
        "injection_lease_expires_at=NULL, injection_count=0, last_injected_at=NULL, "
        "acknowledged_at=NULL, expired_at=NULL, cancelled_at=NULL, "
        "wake_attempt_count=0, last_wake_at=NULL "
        "WHERE session_message_recipients.state='cancelled'",
        values,
    )


def bind_launch_to_session(
    conn: Any,
    *,
    launch: LaunchRecord,
    session_id: str,
    facts: dict[str, Any],
    now: str,
    wake_after: str,
) -> LaunchRecord:
    """Bind one exact session and make its launch instruction deliverable.

    Binding is also where the launch's model ask reaches the session row.
    The child process cannot be relied on to carry it — a pre-warmed
    harness pool serves the launch from a process older than the launch
    itself — while the launch record has held the exact request since it
    was created.
    """
    require_exact_launch_session(launch, session_id, facts)
    hold_launch_registration_grace(conn, session_id, now=now)
    _extend_message_expiry(
        conn, message_id=launch.message_id, expires_at=launch.deadline_at
    )
    stamped = stamp_launch_requested_facts(conn, launch=launch, session_id=session_id)
    _insert_pending_recipient(
        conn,
        launch=launch,
        session_id=session_id,
        facts=facts,
        now=now,
        wake_after=wake_after,
    )
    return update_launch(
        conn,
        launch.launch_id,
        registered_session_id=session_id,
        attestation_consumed_at=now,
        result_code="registration_bound",
        result_evidence=bound_registration_evidence(
            launch, facts["model"], stamped_columns=stamped
        ),
    )


def bind_existing_registered_session(
    conn: Any,
    *,
    launch: LaunchRecord,
    now: str,
) -> LaunchRecord:
    """Bind a native session that registered before relay correlation finished."""
    session_id = str(launch.native_session_id or "").strip()
    if (
        launch.state != "awaiting_registration"
        or not session_id
        or launch.registered_session_id
    ):
        return launch
    facts = registered_session_facts(conn, session_id)
    if facts is None or facts["ended_at"]:
        return launch
    try:
        return bind_launch_to_session(
            conn,
            launch=launch,
            session_id=session_id,
            facts=facts,
            now=now,
            wake_after=now,
        )
    except (SessionLaunchError, SessionError) as exc:
        refusal_code = str(exc.code).lower()
        evidence = {
            "registration_refusal_code": refusal_code,
            "registration_session_id": session_id,
        }
        return update_launch(
            conn,
            launch.launch_id,
            result_code=refusal_code,
            result_evidence=merge_redacted_evidence(launch.result_evidence, evidence),
        )


__all__ = [
    "adopt_attested_session_identity",
    "bind_existing_registered_session",
    "bind_launch_to_session",
    "require_registered_session_facts",
]
