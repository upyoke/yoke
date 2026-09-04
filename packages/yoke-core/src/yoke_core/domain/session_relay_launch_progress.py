"""Persist launch-process progress without settling the native outcome."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.session_control.launch_registration import (
    IDENTITY_REGISTRATION_WAIT_CODE,
    LAUNCH_ADAPTER_STARTED_CODE,
)
from yoke_core.domain.session_launch_native_progress import native_launch_updates
from yoke_core.domain.session_launch_registration_candidate import (
    wait_for_launch_registration_candidate,
)
from yoke_core.domain.session_launch_store import get_launch, update_launch
from yoke_core.domain.session_relay_evidence import (
    merge_redacted_evidence,
    redacted_evidence_document,
)
from yoke_core.domain.session_relay_storage import marker
from yoke_core.domain.session_relay_types import SessionRelayError


def report_launch_progress(
    conn: Any,
    *,
    relay_id: str,
    launch_id: str,
    lease_id: str,
    adapter_revision: str | None,
    evidence: Mapping[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    """Merge safe attempt facts and project native supervision state."""
    p = marker(conn)
    row = conn.execute(
        "SELECT completed_at,result_code,evidence FROM session_launch_attempts "
        f"WHERE launch_id={p} AND lease_id={p} AND relay_id={p}",
        (launch_id, lease_id, relay_id),
    ).fetchone()
    if row is None:
        raise SessionRelayError(
            "attempt_missing", "this relay holds no such launch attempt lease"
        )
    merged = merge_redacted_evidence(row[2], evidence)
    if str(row[1] or "") == "relay_lease_expired":
        merged = merge_redacted_evidence(merged, {"result_code": "relay_lease_expired"})
    conn.execute(
        "UPDATE session_launch_attempts SET adapter_revision="
        + f"COALESCE({p},adapter_revision),evidence={p} "
        + f"WHERE launch_id={p} AND lease_id={p} AND relay_id={p}",
        (
            str(adapter_revision or "").strip()[:128] or None,
            merged,
            launch_id,
            lease_id,
            relay_id,
        ),
    )
    safe = redacted_evidence_document(evidence)
    updates = native_launch_updates(safe, observed_at=now)
    if str(row[1] or "") == "relay_lease_expired":
        updates["result_evidence"] = merged
    elif safe.get("result_code") == LAUNCH_ADAPTER_STARTED_CODE:
        current = get_launch(conn, launch_id)
        if current.state == "launching":
            updates.update(
                state="awaiting_registration",
                awaiting_registration_at=now,
            )
    launch = update_launch(conn, launch_id, **updates) if updates else None
    conn.commit()
    registration = None
    if safe.get("result_code") == IDENTITY_REGISTRATION_WAIT_CODE:
        registration = wait_for_launch_registration_candidate(
            conn,
            launch_id=launch_id,
            lease_id=lease_id,
            initial_now=now,
        )
        launch = None
    if launch is None:
        launch_row = conn.execute(
            f"SELECT state,result_code FROM session_launches WHERE launch_id={p}",
            (launch_id,),
        ).fetchone()
        state, result_code = str(launch_row[0]), str(launch_row[1] or "")
    else:
        state, result_code = launch.state, str(launch.result_code or "")
    conn.commit()
    result = {"launch_id": launch_id, "state": state, "result_code": result_code}
    if registration is not None:
        result["registration"] = registration
    return result


__all__ = ["report_launch_progress"]
