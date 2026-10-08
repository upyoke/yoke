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

from datetime import datetime

import hmac
from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.launch_registration import (
    SESSION_ENDED_UNBOUND_CODE,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_launch_closure_evidence import closure_evidence
from yoke_core.domain.session_launch_store import (
    attestation_digest,
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
    now: datetime | str,
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


#: Why an ending session wrote nothing onto the launch it names.
SESSION_END_SKIP_ATTESTATION_INVALID = "attestation_invalid"
SESSION_END_SKIP_LAUNCH_BOUND = "launch_bound"
SESSION_END_SKIP_LAUNCH_CLOSED = "launch_closed"
SESSION_END_SKIP_NATIVE_SESSION_MISMATCH = "native_session_mismatch"
SESSION_END_SKIP_EARLIER_REFUSAL = "earlier_refusal_kept"
SESSION_END_RECORDED = "recorded"


def _still_bindable(launch: LaunchRecord) -> bool:
    """Whether a registration could still bind this launch.

    Exactly the eligibility binding applies: a launch awaiting registration,
    or an ``outcome_unknown`` one with no identity yet, which recovery
    adoption still binds. Anything else is not this native's to annotate.
    """
    if launch.state == "awaiting_registration":
        return True
    return (
        launch.state == "outcome_unknown"
        and not launch.native_session_id
        and not launch.registered_session_id
    )


def record_session_ended_unbound(
    conn: Any,
    *,
    launch_id: str,
    attestation: str,
    session_id: str,
) -> str:
    """Name a launch whose attested session ended before it ever bound.

    Recovery adoption runs on the attested session's own hooks. A native that
    ran only while its launch awaited the relay's identity report, then ended,
    leaves no later hook to adopt it, and its pending refusals are deliberately
    unrecorded because they normally resolve on the next event. Its ending is
    the last fact that native can report, so it is written here rather than
    left for a deadline to close with nothing attached.

    Only a session that proves the launch's attestation, and is the launch's
    native when the launch already names one, may write it, only while the
    launch could still bind, and never over a refusal already on the row: an earlier code names the more specific failure. Returns
    ``recorded`` or the named reason nothing was written.
    """
    begin_mutation(conn)
    try:
        launch = get_launch(conn, launch_id, for_update=True)
        expected = str(launch.attestation_hash or "")
        if not expected or not hmac.compare_digest(
            expected, attestation_digest(attestation)
        ):
            outcome = SESSION_END_SKIP_ATTESTATION_INVALID
        elif str(launch.registered_session_id or "").strip():
            outcome = SESSION_END_SKIP_LAUNCH_BOUND
        elif str(launch.native_session_id or "").strip() not in ("", session_id):
            # The launch already names its native; another session carrying
            # the inherited attestation is not that native's to speak for.
            outcome = SESSION_END_SKIP_NATIVE_SESSION_MISMATCH
        elif not _still_bindable(launch):
            outcome = SESSION_END_SKIP_LAUNCH_CLOSED
        elif _recorded_refusal(launch.result_evidence):
            outcome = SESSION_END_SKIP_EARLIER_REFUSAL
        else:
            update_launch(
                conn,
                launch_id,
                result_evidence=merge_redacted_evidence(
                    launch.result_evidence,
                    {
                        "registration_refusal_code": SESSION_ENDED_UNBOUND_CODE,
                        "registration_session_id": session_id,
                    },
                ),
            )
            outcome = SESSION_END_RECORDED
        conn.commit()
        return outcome
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "bound_registration_evidence",
    "late_registration_evidence",
    "record_registration_refusal",
    "record_session_ended_unbound",
    "SESSION_END_RECORDED",
    "SESSION_END_SKIP_ATTESTATION_INVALID",
    "SESSION_END_SKIP_EARLIER_REFUSAL",
    "SESSION_END_SKIP_LAUNCH_BOUND",
    "SESSION_END_SKIP_LAUNCH_CLOSED",
    "SESSION_END_SKIP_NATIVE_SESSION_MISMATCH",
]
