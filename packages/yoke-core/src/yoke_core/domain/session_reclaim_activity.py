"""Shared stale-reclaim activity classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from . import db_backend
from .session_staleness import activity_is_stale
from .sessions_analytics_core import DEFAULT_STALE_THRESHOLD_MINUTES
from .sessions_render_reclaim import _resolve_effective_ttl
from .schema_common import _get_columns as _schema_get_columns


SCOPE_ITEM_CLAIM = "item_claim"
SCOPE_SESSION_CLEANUP = "session_cleanup"

REASON_ENDED = "ended"
REASON_NEVER_ENGAGED = "never_engaged"
REASON_HEARTBEAT_STALE = "heartbeat_stale"
REASON_PROGRESS_STALE = "progress_stale"
REASON_FRESH = "fresh"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass(frozen=True)
class ReclaimActivityEvidence:
    session_id: str
    executor: str
    effective_ttl_minutes: int
    last_heartbeat: Optional[str]
    last_event_at: Optional[str]
    claim_last_heartbeat: Optional[str]
    claim_claimed_at: Optional[str]
    activity_at: Optional[str]
    ended_at: Optional[str]

    def as_payload(self) -> dict:
        return {
            "executor": self.executor,
            "effective_ttl_minutes": self.effective_ttl_minutes,
            "last_heartbeat": self.last_heartbeat,
            "last_event_at": self.last_event_at,
            "claim_last_heartbeat": self.claim_last_heartbeat,
            "claim_claimed_at": self.claim_claimed_at,
            "activity_at": self.activity_at,
        }


@dataclass(frozen=True)
class ReclaimClassification:
    is_reclaimable: bool
    reason: str
    evidence: ReclaimActivityEvidence


def resolve_effective_ttl(
    executor: Optional[str],
    *,
    base_ttl_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    overrides: Optional[Mapping[str, int]] = None,
) -> int:
    """Return the effective stale TTL minutes for ``executor``."""
    return _resolve_effective_ttl(
        executor,
        base_ttl_minutes,
        dict(overrides) if overrides is not None else None,
    )


def _session_state(
    conn: Any, session_id: str
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return ``(executor, last_heartbeat, ended_at, last_tool_call_at)``.

    ``last_tool_call_at`` is the post telemetry-only-events tool-activity signal — stamped by
    the observe pipeline in the same transaction as each tool-call
    telemetry insert. Introspection keeps minimal fixtures working: a
    schema lacking the column (or the optional executor) reads as NULL.
    """
    try:
        columns = set(_schema_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types():
        return (None, None, None, None)
    if not columns:
        return (None, None, None, None)
    select_cols = ["last_heartbeat", "ended_at"]
    if "executor" in columns:
        select_cols.insert(0, "executor")
    if "last_tool_call_at" in columns:
        select_cols.append("last_tool_call_at")
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM harness_sessions "
            f"WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types():
        return (None, None, None, None)
    if row is None:
        return (None, None, None, None)
    values = (
        {name: row[name] for name in select_cols}
        if hasattr(row, "keys")
        else dict(zip(select_cols, row))
    )
    return (
        values.get("executor"),
        values.get("last_heartbeat"),
        values.get("ended_at"),
        values.get("last_tool_call_at"),
    )


def _claim_state(
    conn,
    session_id: str,
    claim_id: Optional[int] = None,
) -> tuple[Optional[str], Optional[str]]:
    try:
        columns = set(_schema_get_columns(conn, "work_claims"))
    except db_backend.operational_error_types():
        return (None, None)
    if not columns:
        return (None, None)
    heartbeat_col = "last_heartbeat" if "last_heartbeat" in columns else None
    if claim_id is not None:
        select_cols = "claimed_at"
        if heartbeat_col:
            select_cols = "last_heartbeat, " + select_cols
        p = _p(conn)
        row = conn.execute(
            f"""SELECT {select_cols}
                FROM work_claims
                WHERE id = {p} AND session_id = {p} AND released_at IS NULL""",
            (claim_id, session_id),
        ).fetchone()
    else:
        select_cols = "MAX(claimed_at) AS claimed_at"
        if heartbeat_col:
            select_cols = "MAX(last_heartbeat) AS last_heartbeat, " + select_cols
        p = _p(conn)
        row = conn.execute(
            f"""SELECT {select_cols}
                FROM work_claims
                WHERE session_id = {p} AND released_at IS NULL""",
            (session_id,),
        ).fetchone()
    if row is None:
        return (None, None)
    if heartbeat_col and hasattr(row, "keys"):
        return (row["last_heartbeat"], row["claimed_at"])
    if heartbeat_col:
        return (row[0], row[1])
    if hasattr(row, "keys"):
        return (None, row["claimed_at"])
    return (None, row[0])


def read_activity_signals(
    conn: Any,
    session_id: str,
    *,
    claim_id: Optional[int] = None,
    base_ttl_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    overrides: Optional[Mapping[str, int]] = None,
) -> ReclaimActivityEvidence:
    """Read the canonical reclaim activity signals for ``session_id``."""
    executor_raw, last_heartbeat, ended_at, last_event_at = _session_state(
        conn, session_id,
    )
    claim_last_heartbeat, claim_claimed_at = _claim_state(
        conn, session_id, claim_id,
    )

    candidates = [
        t for t in (
            claim_last_heartbeat,
            claim_claimed_at,
            last_heartbeat,
            last_event_at,
        ) if t
    ]
    activity_at = max(candidates) if candidates else None

    executor = executor_raw if executor_raw else "unknown"
    effective_ttl = resolve_effective_ttl(
        executor,
        base_ttl_minutes=base_ttl_minutes,
        overrides=overrides,
    )
    return ReclaimActivityEvidence(
        session_id=session_id,
        executor=executor,
        effective_ttl_minutes=effective_ttl,
        last_heartbeat=last_heartbeat,
        last_event_at=last_event_at,
        claim_last_heartbeat=claim_last_heartbeat,
        claim_claimed_at=claim_claimed_at,
        activity_at=activity_at,
        ended_at=ended_at,
    )


def latest_activity(
    conn: Any,
    session_id: str,
    *,
    executor: Optional[str] = None,
) -> Optional[str]:
    """Return the canonical "is this session alive?" timestamp."""
    del executor  # routed via read_activity_signals
    return read_activity_signals(conn, session_id).activity_at


def classify_reclaimable(
    conn: Any,
    session_id: str,
    *,
    claim_id: Optional[int] = None,
    base_ttl_minutes: int = DEFAULT_STALE_THRESHOLD_MINUTES,
    overrides: Optional[Mapping[str, int]] = None,
    progress_threshold_minutes: Optional[int] = None,
) -> ReclaimClassification:
    """Classify whether ``session_id`` is reclaimable right now."""
    evidence = read_activity_signals(
        conn,
        session_id,
        claim_id=claim_id,
        base_ttl_minutes=base_ttl_minutes,
        overrides=overrides,
    )

    if evidence.ended_at is not None:
        return ReclaimClassification(
            is_reclaimable=True,
            reason=REASON_ENDED,
            evidence=evidence,
        )

    overrides_dict = dict(overrides) if overrides is not None else None
    heartbeat_stale = activity_is_stale(
        evidence.last_heartbeat,
        executor=evidence.executor,
        base_ttl_minutes=base_ttl_minutes,
        executor_ttl_overrides=overrides_dict,
    )
    event_stale = activity_is_stale(
        evidence.last_event_at,
        executor=evidence.executor,
        base_ttl_minutes=base_ttl_minutes,
        executor_ttl_overrides=overrides_dict,
    )
    claim_heartbeat_stale = activity_is_stale(
        evidence.claim_last_heartbeat,
        executor=evidence.executor,
        base_ttl_minutes=base_ttl_minutes,
        executor_ttl_overrides=overrides_dict,
    )
    claim_claimed_stale = activity_is_stale(
        evidence.claim_claimed_at,
        executor=evidence.executor,
        base_ttl_minutes=base_ttl_minutes,
        executor_ttl_overrides=overrides_dict,
    )

    if (
        heartbeat_stale
        and event_stale
        and claim_heartbeat_stale
        and claim_claimed_stale
    ):
        if evidence.activity_at is None:
            reason = REASON_NEVER_ENGAGED
        else:
            reason = REASON_HEARTBEAT_STALE
        return ReclaimClassification(
            is_reclaimable=True,
            reason=reason,
            evidence=evidence,
        )

    if (
        progress_threshold_minutes is not None
        and evidence.last_event_at is not None
    ):
        progress_stale = activity_is_stale(
            evidence.last_event_at,
            executor=evidence.executor,
            base_ttl_minutes=progress_threshold_minutes,
            executor_ttl_overrides={},
        )
        if progress_stale:
            return ReclaimClassification(
                is_reclaimable=True,
                reason=REASON_PROGRESS_STALE,
                evidence=evidence,
            )

    return ReclaimClassification(
        is_reclaimable=False,
        reason=REASON_FRESH,
        evidence=evidence,
    )


__all__ = [
    "ReclaimActivityEvidence", "ReclaimClassification", "SCOPE_ITEM_CLAIM",
    "SCOPE_SESSION_CLEANUP", "REASON_ENDED", "REASON_FRESH",
    "REASON_HEARTBEAT_STALE", "REASON_NEVER_ENGAGED",
    "REASON_PROGRESS_STALE", "resolve_effective_ttl",
    "read_activity_signals", "classify_reclaimable", "latest_activity",
]
