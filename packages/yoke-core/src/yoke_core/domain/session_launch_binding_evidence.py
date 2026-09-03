"""Evidence for launch registrations the control plane refuses or reshapes.

A native that came up, ran its hook, and was turned away at the binding
boundary looks — from the launch row alone — exactly like a native that never
started: both end at the deadline with a terminal code and nothing else. The
two need entirely different repairs, so the refusal itself is written onto the
launch while it is still true.

Model-selection labels get requested/registered pairs because a launch's
model, reasoning effort, and context window are requests while the session's
plain fields are measurements, and the two legitimately differ. Comparing
them for equality would refuse a correctly bound launch, so bind identity
ignores selection differences and records both values instead. These pairs
are launch diagnostics, not a second roster, and served session fields are
never overwritten with requests.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import json_helper
from yoke_core.domain.session_launch_closure_evidence import closure_evidence
from yoke_core.domain.session_launch_store import (
    begin_mutation,
    get_launch,
    update_launch,
)
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence
from yoke_core.domain.session_launch_types import LaunchRecord


def bound_registration_evidence(
    launch: LaunchRecord,
    registered_facts: Mapping[str, Any],
    *,
    stamped_columns: Sequence[str] = (),
) -> str:
    """Record the ask beside the served value when the two differ.

    ``registered_facts`` are the session row's attested served values, so a
    launch that asked for one selection and ran another is visible as a fact
    rather than a suspicion. An unattested value records no label rather than
    an invented mismatch.

    ``stamped_columns`` names the requested columns the binding wrote onto
    the session from this launch. A session that carried its own ask leaves
    it empty, so the two ways a request reaches the roster stay tellable
    apart when one of them stops working.
    """
    labels: dict[str, Any] = {}
    for name in ("model", "reasoning_effort", "context_window_tokens"):
        requested = getattr(launch, f"requested_{name}")
        registered = registered_facts.get(name)
        if requested is not None and registered is not None and requested != registered:
            labels[f"requested_{name}"] = requested
            labels[f"registered_{name}"] = registered
    if stamped_columns:
        labels["stamped_requested_columns"] = ",".join(stamped_columns)
    return merge_redacted_evidence(launch.result_evidence, labels)


def late_registration_evidence(
    conn: Any,
    *,
    launch: LaunchRecord,
    session_id: str,
    now: str,
) -> str:
    """Say which session registered too late, and how far the launch got."""
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
    document["registration_session_id"] = session_id
    return merge_redacted_evidence(launch.result_evidence, document)


def _recorded_refusal(stored_evidence: Any) -> str:
    """Return the refusal code already recorded on this launch, if any."""
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
) -> LaunchRecord:
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
            evidence["registration_session_id"] = str(session_id).strip()
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
