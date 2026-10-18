"""Observe native turn completion when the surface did not report a hook.

A native turn can end while its recorded posture remains running. Reading the
surface's own turn record lets its machine stamp the observed completion.
Stale recipients without an idle message route can already use stopped resume;
this observation also makes claim holders reachable before any message arrives.

The control plane names live claim holders and sessions with recorded operation
refusals on surfaces that declare a readable turn record. Only the owning
machine reads and applies that evidence. Newer posture observations supersede
it, and sessions leave the bounded probe set after their turn end is recorded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.session_control.native_turn_end import (
    NATIVE_TURN_END_POSTURE,
    NATIVE_TURN_RECORD_SURFACES,
)
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_scope_identity import relay_serves_scope
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    utc_now,
)
from yoke_core.domain.session_turn_posture import stamp_turn_posture


#: Event recording one session reclassified from its native turn record.
EVENT_SESSION_TURN_END_OBSERVED = "HarnessSessionTurnEndObserved"

#: Most sessions a single poll asks one machine to read back. A machine
#: with more stuck sessions than this gets the rest on its next poll; the
#: cap keeps one degraded machine from turning a poll into a file sweep.
MAX_PROBE_TARGETS = 25

_SESSION_COLUMNS = (
    "session_id, project_id, org_id, actor_id, machine_id, executor_surface, turn_posture, "
    "ended_at, terminated_at"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


#: The part of the session test both probe sets share: this machine's own
#: live sessions, on a surface that declares a readable record, whose end
#: has not already been observed.
_READABLE_LIVE_SESSION = (
    "hs.ended_at IS NULL AND hs.terminated_at IS NULL "
    "AND hs.turn_posture<>{marker} "
    "AND hs.machine_id={marker} "
    "AND hs.executor_surface IN ({surfaces}) "
    "AND ({scope})"
)


def _live_session_clause(
    marker: str, *, projects: Sequence[int], relay_actor_id: int | None
) -> str:
    scopes = (
        [f"hs.project_id IN ({','.join(marker for _ in projects)})"] if projects else []
    )
    if relay_actor_id is not None:
        scopes.append(f"(hs.org_id IS NOT NULL AND hs.actor_id={marker})")
    return _READABLE_LIVE_SESSION.format(
        marker=marker,
        surfaces=",".join(marker for _ in NATIVE_TURN_RECORD_SURFACES),
        scope=" OR ".join(scopes),
    )


def _live_session_params(
    machine_id: str, *, projects: Sequence[int], relay_actor_id: int | None
) -> tuple[Any, ...]:
    return (
        NATIVE_TURN_END_POSTURE,
        machine_id,
        *NATIVE_TURN_RECORD_SURFACES,
        *projects,
        *((relay_actor_id,) if relay_actor_id is not None else ()),
    )


def probe_targets(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    relay_actor_id: int | None = None,
    now: datetime | None = None,
) -> List[Dict[str, str]]:
    """Name this machine's sessions worth reading a turn record back for.

    Two sets, unioned. The first is every session holding an unreleased
    work claim: a worker whose turn died silently is holding an item
    nobody else can take, and nothing else will reveal that until someone
    tries to talk to it. The second is every session whose wake has
    already been refused for want of a supported operation — the shape
    that first exposed this, kept because it catches a stuck session that
    holds no claim.

    Both sets are narrowed by the same three facts: the session is this
    machine's and still live, its surface declares a readable record, and
    its posture is not already the observed-turn-end one. That last
    condition is what makes repeated polling cheap and idempotent — a
    session leaves the set as soon as its end is recorded.
    """
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    if not machine_id or (not projects and relay_actor_id is None):
        return []
    current = parse_instant(utc_now() if now is None else now)
    stamped = instant_parameter(conn, current)
    marker = _p(conn)
    live = _live_session_clause(
        marker, projects=projects, relay_actor_id=relay_actor_id
    )
    live_params = _live_session_params(
        machine_id, projects=projects, relay_actor_id=relay_actor_id
    )
    claim_holders = conn.execute(
        "SELECT DISTINCT hs.session_id,hs.executor_surface "
        "FROM harness_sessions hs "
        "JOIN work_claims wc ON wc.session_id=hs.session_id "
        "AND wc.released_at IS NULL "
        f"WHERE {live} "
        "ORDER BY hs.session_id",
        live_params,
    ).fetchall()
    refused_wakes = conn.execute(
        "SELECT DISTINCT hs.session_id,hs.executor_surface "
        "FROM harness_sessions hs "
        "JOIN session_message_recipients r ON r.session_id=hs.session_id "
        "AND r.state='pending' "
        "JOIN session_messages m ON m.message_id=r.message_id "
        f"AND m.cancelled_at IS NULL AND m.expires_at>{marker} "
        "JOIN session_message_attempts a ON a.target_session_id=hs.session_id "
        "AND a.message_id=r.message_id AND a.attempt_kind='wake_relay' "
        "AND a.result_code='skipped_operation' "
        f"WHERE {live} "
        "ORDER BY hs.session_id",
        (stamped, *live_params),
    ).fetchall()
    targets: Dict[str, Dict[str, str]] = {}
    for raw in list(claim_holders) + list(refused_wakes):
        entry = row_dict(raw)
        session_id = str(entry["session_id"])
        targets.setdefault(
            session_id,
            {
                "session_id": session_id,
                "executor_surface": str(entry["executor_surface"]),
            },
        )
    return [targets[key] for key in sorted(targets)][:MAX_PROBE_TARGETS]


def _session_row(conn: Any, session_id: str) -> Dict[str, Any] | None:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT {_SESSION_COLUMNS} FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    return None if row is None else row_dict(row)


def _skip_reason(
    row: Dict[str, Any] | None,
    *,
    machine_id: str,
    authorized_projects: Sequence[int],
    relay_actor_id: int | None = None,
) -> str | None:
    """Name why a reported turn end must not be applied, or ``None`` to apply."""
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    if not relay_serves_scope(
        relay_machine_id=machine_id,
        relay_actor_id=relay_actor_id,
        advertised_project_ids=authorized_projects,
        row_machine_id=row.get("machine_id"),
        row_project_id=row.get("project_id"),
        row_org_id=row.get("org_id"),
        row_actor_id=row.get("actor_id"),
    ):
        return "project_unauthorized"
    if str(row.get("executor_surface") or "") not in NATIVE_TURN_RECORD_SURFACES:
        # Every other surface's turn end stamps itself, so a report about
        # one is evidence from the wrong place.
        return "surface_without_turn_record"
    if row.get("ended_at") or row.get("terminated_at"):
        return "session_terminal"
    return None


def _record_observed(
    conn: Any,
    session_id: str,
    *,
    evidence: Mapping[str, Any],
    observed_at: datetime | None,
    recorded_at: datetime,
) -> None:
    """Store the observation on the session, then publish its telemetry.

    Recovery reads the stored copy. It used to read the event, which made
    a stopped worker unrecoverable — and unexplainable — the moment that
    row expired, while ``turn_posture`` still said the turn had ended.
    The event stays as telemetry; it is no longer the only place the
    provider's own words are kept.
    """
    from yoke_core.domain.events import emit_event
    from yoke_core.domain.session_recovery_facts import record_native_turn_end

    observation = {
        "session_id": session_id,
        "observed_at": format_instant(observed_at) if observed_at is not None else None,
        "posture": NATIVE_TURN_END_POSTURE,
        "source": "relay_native_turn_record",
        **dict(evidence),
    }
    record_native_turn_end(
        conn,
        session_id,
        observation=observation,
        recorded_at=recorded_at,
    )
    emit_event(
        EVENT_SESSION_TURN_END_OBSERVED,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        context=observation,
        conn=conn,
    )


def apply_native_turn_ends(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    relay_actor_id: int | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Apply one machine's observed turn ends and name every refusal.

    Stamping is ordered against every other posture observation by the
    record's own timestamp, so a session that took a real turn after the
    error keeps the newer ``running`` and is left alone. Anything not
    applied comes back with a named status: a silent no-op here reads
    exactly like the stuck session this path exists to free.
    """
    current = parse_instant(utc_now() if now is None else now)
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    reclassified: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for report in reports:
        session_id = str(report.get("session_id") or "").strip()
        if not session_id:
            continue
        row = _session_row(conn, session_id)
        status = _skip_reason(
            row,
            machine_id=machine_id,
            authorized_projects=projects,
            relay_actor_id=relay_actor_id,
        )
        if status is None:
            observed_at = parse_timestamp(report.get("observed_at"))
            stamped = stamp_turn_posture(
                conn,
                session_id=session_id,
                posture=NATIVE_TURN_END_POSTURE,
                observed_at=current if observed_at is None else observed_at,
            )
            if not stamped:
                # A newer posture observation already won, which means the
                # session took a turn after the record this report read.
                status = "posture_superseded"
            else:
                _record_observed(
                    conn,
                    session_id,
                    evidence=report.get("evidence") or {},
                    observed_at=observed_at,
                    recorded_at=current,
                )
        if status is None:
            reclassified.append(session_id)
        else:
            skipped.append({"session_id": session_id, "status": status})
    return {"reclassified": reclassified, "skipped": skipped}


__all__ = [
    "EVENT_SESSION_TURN_END_OBSERVED",
    "MAX_PROBE_TARGETS",
    "apply_native_turn_ends",
    "probe_targets",
]
