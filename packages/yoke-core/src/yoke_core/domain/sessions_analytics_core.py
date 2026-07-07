"""Session analytics constants, registry seeding, and base emitters."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from . import db_backend
from .runtime_settings import get_int
from .schema_common import _table_exists

logger = logging.getLogger(__name__)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class SessionError(Exception):
    """Raised when a session operation violates a business rule."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Constants — TTLs sourced from machine config so prose/code share one tunable.
# ---------------------------------------------------------------------------

DEFAULT_STALE_THRESHOLD_MINUTES = get_int("session_stale_ttl_minutes", 20)
DEFAULT_PROGRESS_THRESHOLD_MINUTES = 90
EXECUTOR_STALE_TTL_OVERRIDES_MINUTES: Dict[str, int] = {
    "codex": get_int("session_stale_ttl_minutes_codex_override", 60),
}


# ---------------------------------------------------------------------------
# Event names — registered in event_registry
# ---------------------------------------------------------------------------

EVENT_HARNESS_SESSION_STARTED = "HarnessSessionStarted"
EVENT_HARNESS_SESSION_ENDED = "HarnessSessionEnded"
EVENT_WORK_CLAIMED = "WorkClaimed"
EVENT_WORK_RELEASED = "WorkReleased"
EVENT_WORK_RECLAIMED = "WorkReclaimed"
EVENT_RECLAIM_ABORTED = "ReclaimAborted"
EVENT_WORK_HANDED_OFF = "WorkHandedOff"
EVENT_CHAIN_STEP_COMPLETED = "ChainStepCompleted"


EVENT_HARNESS_SESSION_HOOK_FAILED = "HarnessSessionHookFailed"
EVENT_HARNESS_SESSION_STALE_RECLAIMED = "HarnessSessionStaleReclaimed"
EVENT_HARNESS_SESSION_END_REJECTED_ACTIVE_CLAIM = "HarnessSessionEndRejectedActiveClaim"
EVENT_OPERATOR_CLAIM_OVERRIDE = "OperatorClaimOverride"
EVENT_HARNESS_SESSION_STALE_SWEEP_COMPLETED = "HarnessSessionStaleSweepCompleted"
EVENT_HARNESS_SESSION_END_RELEASED_CLAIMS = "HarnessSessionEndReleasedClaims"
EVENT_ITEM_CLAIM_RELEASE_FAILED = "ItemClaimReleaseFailed"
EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS = "SessionReactivatedWithReleasedClaims"
EVENT_HARNESS_SESSION_END_DEFERRED = "HarnessSessionEndDeferred"
EVENT_SESSION_REACTIVATION_REACQUIRED_CLAIMS = "SessionReactivationReacquiredClaims"
EVENT_HARNESS_SESSION_RESUME_BLOCK_SHOWN = "HarnessSessionResumeBlockShown"


# Idempotent event registry seed rows. populate-registry discovers callsites,
# but these rows need to exist the first time session lifecycle code is imported
# on a fresh DB (tests, new clones, doctor diagnostics).
_SESSION_EVENT_REGISTRY_ROWS = (
    (
        "HarnessSessionHookFailed",
        "system",
        "session_hook_failure",
        "api",
        (
            "Emitted when a Claude/Codex Stop or SessionEnd hook fails to complete "
            "cleanly (DB contention or cleanup exception). Carries "
            "hook_event, executor, reason, latency_ms, stdin_state, session_id_source."
        ),
        "WARN",
        "session-hook-failure-registry",
    ),
    (
        "HarnessSessionStaleReclaimed",
        "system",
        "session_lifecycle",
        "api",
        (
            "Emitted by the shared stale-session reclaimer when an idle session is "
            "force-ended. Carries stale_minutes, last_event_at, released_claim_count, "
            "executor, reason."
        ),
        "INFO",
        "stale-session-reclaimer-registry",
    ),
    (
        "HarnessSessionEndRejectedActiveClaim",
        "system",
        "session_lifecycle",
        "api",
        (
            "Emitted when end_session() rejects termination because the session "
            "holds an active unreleased claim. Carries session_id, claim_id, "
            "item_id, task_num, heartbeat_age_s, hook_path."
        ),
        "WARN",
        "active-claim-end-guard",
    ),
    (
        "OperatorClaimOverride",
        "system",
        "session_lifecycle",
        "api",
        (
            "Emitted when an operator manually releases a stranded claim via "
            "the human-only override CLI. Carries claim_id, item_id, session_id, "
            "operator_reason, release_reason_intent."
        ),
        "WARN",
        "operator-claim-override",
    ),
    (
        "HarnessSessionStaleSweepCompleted",
        "system",
        "session_lifecycle",
        "api",
        (
            "Emitted after every stale-session sweep run, even when zero sessions "
            "were reclaimed. Carries total_scanned, total_reclaimed, sweep_duration_ms."
        ),
        "INFO",
        "stale-session-sweep",
    ),
    (
        "HarnessSessionEndReleasedClaims",
        "system",
        "session_lifecycle",
        "api",
        (
            "Emitted when end_session(release_claims=True) auto-releases active "
            "claims before ending the session (SessionEnd hook path). Carries "
            "session_id, released_count, claim_details."
        ),
        "INFO",
        "session-end-claim-release",
    ),
    (
        "SessionReactivatedWithReleasedClaims",
        "system",
        "session_lifecycle",
        "yoke_core.domain.sessions_lifecycle_reactivation",
        (
            "Emitted when a session is reactivated (ended_at cleared) and prior "
            "work_claims with release_reason='session_ended' exist for that session. "
            "Surface event for the slim resume block; paired with "
            "SessionReactivationReacquiredClaims when conditional auto-reacquire "
            "runs. Carries session_id, released_claim_count, released_claims list "
            "of {target_kind, item_id, epic_id, task_num} tuples."
        ),
        "INFO",
        "session-reactivation-release-advisory",
    ),
    (
        "ReclaimAborted",
        "system",
        "session_lifecycle",
        "api",
        (
            "Emitted by the shared reclaim activity classifier when a "
            "stale-eligible holder session shows fresh activity at the "
            "mutation boundary. Carries scope (item_claim or "
            "session_cleanup), original_session_id, attempting_session_id, "
            "claim_id, executor, effective_ttl_minutes, "
            "original_session_last_heartbeat, original_session_last_event_at, "
            "abort_reason."
        ),
        "INFO",
        "stale-session-reclaim-abort",
    ),
    (
        "HarnessSessionEndDeferred",
        "system",
        "session_lifecycle",
        "yoke_core.domain.sessions_lifecycle_destructive_guard",
        (
            "Emitted when end_session(release_claims=True) declines to "
            "release claims because a chainable checkpoint still has "
            "budget. Carries session_id, defer_reason (chain_pending), "
            "agent_presence_evidence (chain_budget_remaining), "
            "active_claim_count, claim_details."
        ),
        "INFO",
        "session-end-chain-deferral",
    ),
    (
        "SessionReactivationReacquiredClaims",
        "system",
        "session_lifecycle",
        "yoke_core.domain.sessions_lifecycle_reactivation",
        (
            "Emitted when register_session reactivation auto-reacquires "
            "prior session_ended claims within "
            "session_reactivation_reacquire_window_s. Carries session_id, "
            "reacquired_count, conflict_count, claim_details "
            "(new_claim_id, target). Paired with the existing advisory "
            "SessionReactivatedWithReleasedClaims event."
        ),
        "INFO",
        "session-reactivation-claim-reacquire",
    ),
    (
        "HarnessSessionResumeBlockShown",
        "system",
        "session_lifecycle",
        "yoke_core.domain.sessions_resume_block",
        (
            "Marker event emitted by the hook runner the first time the "
            "slim resume block is rendered for a reactivation cycle. Used "
            "by the harness UserPromptSubmit / SessionStart dispatcher to "
            "render the block exactly once per reactivation. Carries "
            "session_id, harness_event (UserPromptSubmit|SessionStart), "
            "reactivation_event_id, reacquired, advisory_only."
        ),
        "INFO",
        "session-resume-block",
    ),
)


def ensure_session_event_registry_entries(conn: Any) -> None:
    """Ensure required registry rows exist (idempotent)."""
    try:
        if not _table_exists(conn, "event_registry"):
            return
        for row in _SESSION_EVENT_REGISTRY_ROWS:
            name, kind, etype, service, desc, severity, added_in = row
            p = _p(conn)
            conn.execute(
                "INSERT INTO event_registry ("
                "event_name, event_kind, event_type, owner_service, "
                "description, context_schema, severity_default, added_in, status"
                f") VALUES ({p}, {p}, {p}, {p}, {p}, NULL, {p}, {p}, 'active') "
                "ON CONFLICT(event_name) DO NOTHING",
                (name, kind, etype, service, desc, severity, added_in),
            )
        conn.commit()
    except db_backend.database_error_types(conn):
        # Telemetry convenience — never block the caller
        return


# ---------------------------------------------------------------------------
# Event emission helper — native Python emitter
# ---------------------------------------------------------------------------


def _emit_event(
    event_name: str,
    *,
    event_kind: str,
    event_type: str,
    source_type: str,
    session_id: str,
    project: Optional[str] = None,
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    outcome: str = "completed",
    severity: str = "INFO",
) -> None:
    """Emit a structured event via the native Python emitter (non-fatal).

    Delegates to ``yoke_core.domain.events.emit_event`` which writes
    directly to the ``events`` table.  Falls back silently on any failure.
    """
    try:
        from .events import emit_event as _native_emit
        _native_emit(
            event_name,
            event_kind=event_kind,
            event_type=event_type,
            source_type=source_type,
            session_id=session_id,
            project=project or "yoke",
            severity=severity,
            outcome=outcome,
            item_id=item_id,
            task_num=task_num,
            context=context,
        )
    except Exception as exc:
        logger.debug("Native event emission failed for %s: %s", event_name, exc)


def _emit_session_event(
    event_name: str,
    *,
    session_id: str,
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
    outcome: str = "completed",
) -> None:
    """Emit a structured session event via the native Python emitter (non-fatal).

    Events are best-effort telemetry — failures are logged but never
    propagate to the caller.

    Args:
        event_name: Registered event name (e.g., ``WorkClaimed``).
        session_id: Session correlation ID.
        item_id: Top-level indexed ``item_id`` (stored bare numeric when possible).
            Populated when the event targets a specific work unit.
        task_num: Top-level indexed ``task_num`` for epic task context.
        context: Envelope detail dict (serialised to JSON).
        outcome: Event outcome string (default ``completed``).
    """
    _emit_event(
        event_name,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        item_id=item_id,
        task_num=task_num,
        context=context,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Telemetry emission functions (session-offer post-decision)
# ---------------------------------------------------------------------------

# Canonical downstream path names keyed by scheduler next_step values.
# Keep this in sync with yoke_core.domain.session._NEXT_STEP_TO_PATH.
_NEXT_STEP_TO_PATH: Dict[str, str] = {
    "refine": "refine",
    "shepherd": "shepherd",
    "conduct": "conduct",
    "advance": "advance",
    "polish": "polish",
    "usher": "usher",
}
