"""Evidence for receipts whose native wake route is unavailable.

A bare ``skipped_operation`` names the answer and hides the question. The
same code covers a surface that has no route for the operation at all, a
peer binary that is not installed, and a driver too old to qualify — and
the reader who needs to tell them apart is looking at a session that has
gone silent. So every skip carries the rule that produced it plus the
posture, liveness, and operation it was reading, which is what turns a
recorded refusal into something an operator can act on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.surface_versions import (
    machine_wake_executor_surface,
    surface_operation_supported,
    surface_version_supported,
)
from yoke_core.domain.session_message_types import timestamp
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.session_surface_policy import (
    WAKE_SKIP_SURFACE_DISABLED,
    live_mark,
)


_WAKE_SKIP_ADAPTER_REVISION = "session-wake-eligibility-v1"


def _wake_skip_result(
    row: Mapping[str, Any],
    operation: str | None,
    relay_versions: Mapping[str, str],
    *,
    conn: Any | None = None,
) -> tuple[str, str | None, str]:
    """Return the recorded code, the driver it named, and the rule that fired."""
    surface = str(row.get("executor_surface") or "")
    machine_id = str(row.get("machine_id") or "")
    if conn is not None and machine_id and surface:
        if live_mark(conn, machine_id, surface) is not None:
            return WAKE_SKIP_SURFACE_DISABLED, None, "surface_policy_disabled"
    capability = capability_for_surface(surface)
    if capability is None:
        return "skipped_surface", None, "surface_unknown"
    if not surface_version_supported(surface, row.get("executor_version")):
        return "skipped_version", None, "surface_version_below_floor"
    if operation is None:
        return "skipped_operation", None, "wake_operation_unresolved"
    driver = machine_wake_executor_surface(surface, operation)
    if driver is not None:
        driver_version = relay_versions.get(driver)
        if not driver_version:
            return "skipped_surface", driver, "peer_driver_not_installed"
        if not surface_operation_supported(driver, driver_version, operation):
            return "skipped_version", driver, "peer_driver_version_below_floor"
    if getattr(capability, operation, "none") == "none":
        return "skipped_operation", driver, "surface_operation_unsupported"
    driver = driver or surface
    driver_version = relay_versions.get(driver)
    if not driver_version:
        return "skipped_surface", driver, "driver_not_installed"
    if not surface_operation_supported(driver, driver_version, operation):
        return "skipped_version", driver, "driver_version_below_floor"
    return "skipped_operation", driver, "route_unavailable"


def record_wake_skip(
    conn: Any,
    row: Mapping[str, Any],
    *,
    operation: str | None,
    relay_versions: Mapping[str, str],
    liveness: str,
    now: datetime,
) -> None:
    message_id = str(row["message_id"])
    session_id = str(row["session_id"])
    result_code, driver, reason = _wake_skip_result(
        row, operation, relay_versions, conn=conn
    )
    driver_version = relay_versions.get(driver or "")
    evidence = {
        "result_code": result_code,
        "skip_reason": reason,
        "wake_operation": str(operation or ""),
        "turn_posture": str(row.get("turn_posture") or ""),
        "liveness": liveness,
        "surface": str(row.get("executor_surface") or ""),
        "driver_surface": str(driver or ""),
        "driver_version": str(driver_version or ""),
    }
    placeholder = marker(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,adapter_revision,"
        "started_at,completed_at,result_code,evidence) "
        f"VALUES ({','.join(placeholder for _ in range(9))}) "
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


__all__ = ["record_wake_skip"]
