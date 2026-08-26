"""Posture- and idle-keyed wake eligibility for durable message receipts."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.surface_versions import (
    machine_wake_executor_surface,
    surface_operation_supported,
    surface_version_supported,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_activity_state import native_thread_id_column_present
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_delivery import (
    _begin_mutation,
    _expire_rows,
)
from yoke_core.domain.session_message_routing import (
    latest_observed_activity,
    messageability,
    session_liveness,
)
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    machine_surface_versions,
)
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_versions import wake_operation


_WAKE_SKIP_ADAPTER_REVISION = "session-wake-eligibility-v1"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _wake_skip_result(
    row: Mapping[str, Any],
    operation: str | None,
    relay_versions: Mapping[str, str],
) -> tuple[str, str | None]:
    surface = str(row.get("executor_surface") or "")
    capability = capability_for_surface(surface)
    if capability is None:
        return "skipped_surface", None
    if not surface_version_supported(surface, row.get("executor_version")):
        return "skipped_version", None
    if operation is None:
        return "skipped_operation", None
    driver = machine_wake_executor_surface(surface, operation)
    if driver is not None:
        driver_version = relay_versions.get(driver)
        if not driver_version:
            return "skipped_surface", driver
        if not surface_operation_supported(driver, driver_version, operation):
            return "skipped_version", driver
    if getattr(capability, operation, "none") == "none":
        return "skipped_operation", driver
    driver = driver or surface
    driver_version = relay_versions.get(driver)
    if not driver_version:
        return "skipped_surface", driver
    if not surface_operation_supported(driver, driver_version, operation):
        return "skipped_version", driver
    return "skipped_operation", driver


def _record_wake_skip(
    conn: Any,
    row: Mapping[str, Any],
    *,
    operation: str | None,
    relay_versions: Mapping[str, str],
    now: datetime,
) -> None:
    message_id = str(row["message_id"])
    session_id = str(row["session_id"])
    result_code, driver = _wake_skip_result(row, operation, relay_versions)
    driver_version = relay_versions.get(driver or "")
    evidence = {
        "result_code": result_code,
        "surface": str(row.get("executor_surface") or ""),
        "driver_surface": str(driver or ""),
        "driver_version": str(driver_version or ""),
    }
    marker = _p(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,adapter_revision,"
        "started_at,completed_at,result_code,evidence) "
        f"VALUES ({','.join(marker for _ in range(9))}) "
        "ON CONFLICT(attempt_id) DO NOTHING",
        (
            str(uuid5(NAMESPACE_URL, f"yoke:wake-skip:{message_id}:{session_id}")),
            message_id,
            session_id,
            "wake_relay",
            _WAKE_SKIP_ADAPTER_REVISION,
            timestamp(now),
            timestamp(now),
            result_code,
            redacted_evidence(evidence),
        ),
    )


def _native_wake_route_available(
    conn: Any,
    row: dict[str, Any],
    *,
    liveness: str,
    operation: str | None,
    relay_versions: Mapping[str, str],
) -> bool:
    routing = messageability(
        row, liveness=liveness, machine_surface_versions=relay_versions
    )
    if routing["wake_interface"] != "none":
        return True
    from yoke_core.domain.session_private_route_qualification import (
        PrivateRouteQualificationError,
        qualification_for_message,
    )

    if operation is None:
        return False
    # Exact stage qualification is claim authority for a canonical route gap.
    for route in ("direct", "broker"):
        try:
            if (
                qualification_for_message(conn, row, operation=operation, route=route)
                is not None
            ):
                return True
        except PrivateRouteQualificationError:
            continue
    return False


def wake_eligible_recipients(
    conn: Any,
    *,
    now: datetime | None = None,
    bypass_waiting_retry_cooldown: bool = False,
    ignore_attempt_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return redacted wake routes with their scheduler authority."""
    from yoke_core.hooks.session_message_delivery import wake_eligible

    current = now or utc_now()
    marker = _p(conn)
    open_attempt_filter = ""
    open_attempt_params: tuple[Any, ...] = ()
    if ignore_attempt_id:
        open_attempt_filter = f"AND a.attempt_id<>{marker} "
        open_attempt_params = (ignore_attempt_id,)
    _begin_mutation(conn)
    try:
        _expire_rows(conn, now=current)
        relay_routes = connected_relay_routes(conn, now=current)
        thread_select = (
            ",hs.native_thread_id" if native_thread_id_column_present(conn) else ""
        )
        rows = conn.execute(
            "SELECT r.*,m.created_at AS message_created_at,m.expires_at,"
            "hs.executor,hs.execution_lane,hs.last_heartbeat,"
            "hs.last_tool_call_at,hs.ended_at,hs.terminated_at,hs.turn_posture,"
            f"hs.turn_posture_at{thread_select} "
            "FROM session_message_recipients r "
            "JOIN session_messages m ON m.message_id=r.message_id "
            "JOIN harness_sessions hs ON hs.session_id=r.session_id "
            "WHERE r.state IN ('pending','injected') AND m.cancelled_at IS NULL "
            "AND r.wake_after<="
            + marker
            + " AND m.expires_at>"
            + marker
            + " AND (r.injection_lease_id IS NULL OR ("
            "r.injection_lease_expires_at IS NOT NULL "
            "AND r.injection_lease_expires_at<="
            + marker
            + ")) AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
            "WHERE a.message_id=r.message_id "
            "AND a.target_session_id=r.session_id "
            "AND a.attempt_kind IN ('wake_relay','wake_broker') "
            "AND a.completed_at IS NULL "
            + open_attempt_filter
            + ")"
            + " ORDER BY r.wake_after,r.message_id,r.session_id",
            (
                timestamp(current),
                timestamp(current),
                timestamp(current),
                *open_attempt_params,
            ),
        ).fetchall()
        eligible: list[dict[str, Any]] = []
        for raw in rows:
            row = row_dict(raw)
            policy = project_policy(conn, int(row["project_id"]))
            liveness = session_liveness(row, now=current)
            attempt_count = int(row["wake_attempt_count"] or 0)
            at_limit = attempt_count >= policy.max_wake_attempts
            adopting_final_attempt = bool(
                ignore_attempt_id and attempt_count == policy.max_wake_attempts
            )
            if at_limit and not adopting_final_attempt:
                continue
            if liveness == "active":
                continue
            if row["state"] == "injected" and not policy.reinject_until_acknowledged:
                continue
            waiting_pending = (
                row["state"] == "pending" and row.get("turn_posture") == "waiting"
            )
            idle_window = timedelta(seconds=policy.wake_after_idle_seconds)
            if waiting_pending:
                if row.get("injection_lease_id") is not None:
                    continue
                previous_wake = parse_timestamp(row.get("last_wake_at"))
                if (
                    not bypass_waiting_retry_cooldown
                    and int(row["wake_attempt_count"] or 0) > 0
                    and (previous_wake is None or previous_wake + idle_window > current)
                ):
                    continue
                wake_mode = WakeMode.WAITING
            else:
                if not wake_eligible(
                    recipient_state=str(row["state"]),
                    last_activity_at=latest_observed_activity(row),
                    now=current,
                    idle_threshold=idle_window,
                ):
                    continue
                wake_mode = WakeMode.IDLE_TIMEOUT
            versions = machine_surface_versions(
                relay_routes,
                machine_id=row["machine_id"],
                project_id=row["project_id"],
            )
            operation = wake_operation(wake_mode.value, liveness)
            if not _native_wake_route_available(
                conn,
                row,
                liveness=liveness,
                operation=operation,
                relay_versions=versions,
            ):
                _record_wake_skip(
                    conn,
                    row,
                    operation=operation,
                    relay_versions=versions,
                    now=current,
                )
                continue
            eligible.append(
                {
                    "message_id": str(row["message_id"]),
                    "session_id": str(row["session_id"]),
                    "project_id": int(row["project_id"]),
                    "machine_id": row["machine_id"],
                    "executor_surface": row["executor_surface"],
                    "executor_version": row["executor_version"],
                    "state": str(row["state"]),
                    "wake_mode": wake_mode.value,
                    "liveness": liveness,
                    "turn_posture": str(row["turn_posture"]),
                    "turn_posture_at": row["turn_posture_at"],
                    "last_heartbeat": row["last_heartbeat"],
                    "last_tool_call_at": row["last_tool_call_at"],
                    "ended_at": row["ended_at"],
                    "terminated_at": row["terminated_at"],
                    "wake_after": row["wake_after"],
                    "injection_lease_id": row["injection_lease_id"],
                    "injection_lease_expires_at": row["injection_lease_expires_at"],
                    "last_injected_at": row.get("last_injected_at"),
                    "wake_attempt_count": attempt_count,
                    "last_wake_at": row["last_wake_at"],
                    "native_thread_id": row.get("native_thread_id"),
                }
            )
        conn.commit()
        return eligible
    except Exception:
        conn.rollback()
        raise


__all__ = ["wake_eligible_recipients"]
