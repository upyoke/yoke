"""Settle launch outcomes and retain the creating native's exit."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from yoke_contracts.timestamps import format_instant
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.session_launch_store import (
    LAUNCH_COLUMNS,
    marker,
    row_to_launch,
    update_launch,
)
from yoke_core.domain.session_launch_types import LaunchRecord
from yoke_core.domain.session_relay_evidence import redacted_evidence


_HISTORY_FIELDS = {
    "result_code": "previous_launch_result",
    "closure_reason": "previous_launch_closure_reason",
    "receipt_state": "previous_launch_receipt_state",
    "registration_refusal_code": "previous_launch_registration_refusal_code",
}


def launch_evidence(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        decoded = json_helper.loads_text(str(value))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def settled_launch_evidence(value: Any) -> dict[str, Any]:
    """Retire active closure facts and discard obsolete recovery instructions."""
    evidence = launch_evidence(value)
    for key, history_key in _HISTORY_FIELDS.items():
        if (prior := evidence.pop(key, None)) is not None:
            evidence.setdefault(history_key, prior)
    for key in ("recovery", "sign_in_recovery"):
        evidence.pop(key, None)
    return evidence


def successful_launch_evidence(value: Any) -> dict[str, Any]:
    evidence = settled_launch_evidence(value)
    evidence.pop("native_launch_phase", None)
    return evidence


def settled_native_phase(evidence: Mapping[str, Any]) -> str:
    return "native_exited" if evidence.get("native_exit_at") else "native_running"


def settle_launch_result(
    conn: Any, launch: LaunchRecord, *, state: str, result_code: str,
    evidence: Mapping[str, Any] | None = None, **changes: Any,
) -> LaunchRecord:
    """Replace current closure evidence under the caller's launch lock."""
    if state == "succeeded":
        document = successful_launch_evidence(launch.result_evidence)
        changes["native_launch_phase"] = settled_native_phase(document)
    else:
        document = settled_launch_evidence(launch.result_evidence)
    for key, item in (evidence or {}).items():
        if item is not None:
            document.setdefault(key, item)
    with savepoint(conn, "launch_result_settlement", owns=False):
        return update_launch(
            conn, launch.launch_id, state=state, result_code=result_code,
            result_evidence=redacted_evidence(document), **changes,
        )


def record_launch_native_exit(
    conn: Any, session_id: str, evidence: Mapping[str, Any], *, exited_at: datetime,
) -> bool:
    """Acknowledge the measured exit once the initiating launch holds one."""
    # A resume can share the session and report several dead PIDs. Its
    # measured native PID takes precedence over that wider set.
    reported_pid = evidence.get("native_pid")
    reported_pids = evidence.get("pids")
    if reported_pid is not None:
        reported_pids = (reported_pid,)
    if not isinstance(reported_pids, (list, tuple)):
        return False
    pids = sorted({pid for pid in reported_pids if type(pid) is int and 0 < pid < 2**31})
    if not pids:
        return False

    p = marker(conn)
    placeholders = ", ".join([p] * len(pids))
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    named_launch = evidence.get("launch_id")
    launch_filter = f" AND launch_id={p}" if named_launch else ""
    params = (session_id, *pids, *((named_launch,) if named_launch else ()))
    row = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches "
        f"WHERE registered_session_id={p} AND native_launch_pid IN ({placeholders})"
        f"{launch_filter} ORDER BY created_at DESC LIMIT 1{lock}",
        params,
    ).fetchone()
    if row is None:
        return False
    launch = row_to_launch(row)
    document = launch_evidence(launch.result_evidence)
    if launch.launching_at is not None and exited_at < launch.launching_at:
        return False
    if document.get("native_exit_at"):
        return True
    document["native_exit_at"] = format_instant(exited_at)
    update_launch(
        conn, launch.launch_id, native_launch_phase="native_exited",
        result_evidence=redacted_evidence(document),
    )
    return True
