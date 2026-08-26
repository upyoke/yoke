"""Evidence for launch registrations the control plane refuses or reshapes.

A native that came up, ran its hook, and was turned away at the binding
boundary looks — from the launch row alone — exactly like a native that never
started: both end at the deadline with a terminal code and nothing else. The
two need entirely different repairs, so the refusal itself is written onto the
launch while it is still true.

Model labels get their own pair of fields because they are the one binding
fact the two sides do not share a vocabulary for. A launch requests the string
its native command line accepts (Cursor's variant-qualified
``cursor-grok-4.6-high-fast``); the session registers the concrete model the
harness reports (``grok-4.6``). Comparing those for equality refused every
correctly-bound Cursor launch, so the difference is recorded rather than
enforced — the native session id already proves this is the exact session the
relay created for this launch.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_store import (
    begin_mutation,
    get_launch,
    update_launch,
)
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.session_launch_types import LaunchRecord


def bound_registration_evidence(
    launch: LaunchRecord,
    registered_model: Any,
) -> str:
    """Merge the two model labels in when the request and the session differ."""
    requested = str(launch.requested_model or "").strip()
    registered = str(registered_model or "").strip()
    labels = (
        {"requested_model": requested, "registered_model": registered}
        if requested and registered and requested != registered
        else {}
    )
    return merge_redacted_evidence(launch.result_evidence, labels)


def late_registration_evidence(
    conn: Any,
    *,
    launch: LaunchRecord,
    session_id: str,
    now: str,
) -> str:
    """Say which session registered too late, and how far the launch got."""
    from yoke_core.domain.session_launch_closure_evidence import closure_evidence

    document = closure_evidence(
        conn,
        launch=launch,
        result_code="late_registration",
        closure_reason="registration_after_deadline",
        relay_id=launch.assigned_relay_id,
        machine_id=launch.assigned_machine_id,
        started_at=launch.awaiting_registration_at,
        now=now,
    )
    document["registration_refusal_session_id"] = session_id
    return merge_redacted_evidence(launch.result_evidence, document)


def _recorded_refusal(stored_evidence: Any) -> str:
    """Return the refusal code already recorded on this launch, if any."""
    from yoke_core.domain import json_helper

    try:
        stored = json_helper.loads_text(str(stored_evidence))
    except (TypeError, ValueError):
        return ""
    if not isinstance(stored, dict):
        return ""
    recorded = stored.get("registration_refusal_code")
    return recorded if isinstance(recorded, str) else ""


def record_registration_refusal(
    conn: Any,
    *,
    launch_id: str,
    code: str,
    session_id: str | None,
) -> LaunchRecord | None:
    """Write one refused registration attempt onto its launch, keeping state.

    Only the evidence column moves: a refusal is a diagnosable fact, not a
    state transition, and the attestation sidecar keeps retrying until the
    launch either binds or reaches its deadline. Retrying is also why an
    unchanged code is not rewritten — a permanent refusal is re-attempted on
    every hook the native fires, and one row per tool call would buy nothing
    the first row did not already say.
    """
    refusal = str(code or "").strip() or "unknown"
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        if _recorded_refusal(launch.result_evidence) == refusal:
            conn.commit()
            return launch
        evidence: dict[str, str] = {"registration_refusal_code": refusal}
        if str(session_id or "").strip():
            evidence["registration_refusal_session_id"] = str(session_id).strip()
        result = update_launch(
            conn,
            launch_id,
            result_evidence=merge_redacted_evidence(launch.result_evidence, evidence),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "bound_registration_evidence",
    "late_registration_evidence",
    "record_registration_refusal",
]
