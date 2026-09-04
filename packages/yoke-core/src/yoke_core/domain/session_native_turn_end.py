"""Reclassify a session whose native ended its turn without saying so.

The wake router picks its operation from posture and liveness, and for one
surface both readings can be wrong at once. A ``codex-cli`` turn that ends
on a vendor error — the observed one was "Selected model is at capacity" —
leaves the CLI process alive and fires no ``Stop`` hook, though Codex
configures one and fires it on an ordinary ending. So posture stays
``running`` while the turn is over, liveness ages from ``active`` to
``stale``, and every wake for that session resolves
``message_active`` or ``message_idle``: two operations ``codex-cli`` does
not support. The envelope records ``skipped_operation`` and nothing else
ever happens. One session sat unreachable for fifty minutes holding its
item claim, silent to hook delivery and to the native resume both.

The one route that surface *does* support is the stopped-session resume,
and posture is what selects it. The native's own turn record says whether
the turn is really over, so the fix is to read that record and stamp the
posture the missing hook would have stamped. Nothing downstream changes:
``waiting`` already routes to ``message_stopped``.

Only the machine that ran the native can read that record, so this module
owns the two halves the control plane holds. :func:`probe_targets` names
the sessions worth reading back, and :func:`apply_native_turn_ends`
applies what the machine read, on the machine's authority over its own
sessions and nobody else's.

Waiting for a message to prove the session is stuck is too late. That was
the original trigger — a wake attempt already recorded
``skipped_operation`` — and it only fires once somebody sends the session
something. On 2026-09-03 five workers' turns died on an upstream 404
within eleven minutes and nothing was pending for any of them, so the
control plane learned nothing until a person sent each one a message
twenty minutes later. A worker holding a work item is the case where
silence costs the most and where an observation is worth making
unprompted, so a live claim holder on a surface that keeps a record is
read back on the ordinary poll, alongside the sessions whose wake has
already failed.

The set stays small and self-limiting: only claim holders, only surfaces
that declare a readable record, only sessions whose posture is not already
the observed-turn-end posture — so a session drops out of the set the
moment its end is recorded, and one error-terminal turn is observed
exactly once. :data:`MAX_PROBE_TARGETS` bounds what any single poll asks
one machine to read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from yoke_contracts.session_control.native_turn_end import (
    NATIVE_TURN_END_POSTURE,
    NATIVE_TURN_RECORD_SURFACES,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
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
    "session_id, project_id, machine_id, executor_surface, turn_posture, "
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
    "AND hs.project_id IN ({projects})"
)


def _live_session_clause(marker: str, *, projects: Sequence[int]) -> str:
    return _READABLE_LIVE_SESSION.format(
        marker=marker,
        surfaces=",".join(marker for _ in NATIVE_TURN_RECORD_SURFACES),
        projects=",".join(marker for _ in projects),
    )


def _live_session_params(
    machine_id: str, *, projects: Sequence[int]
) -> tuple[Any, ...]:
    return (
        NATIVE_TURN_END_POSTURE,
        machine_id,
        *NATIVE_TURN_RECORD_SURFACES,
        *projects,
    )


def probe_targets(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
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
    if not projects or not machine_id:
        return []
    marker = _p(conn)
    live = _live_session_clause(marker, projects=projects)
    live_params = _live_session_params(machine_id, projects=projects)
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
        (timestamp(now or utc_now()), *live_params),
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
) -> str | None:
    """Name why a reported turn end must not be applied, or ``None`` to apply."""
    if row is None:
        return "session_not_found"
    if str(row.get("machine_id") or "") != machine_id:
        return "machine_mismatch"
    project_id = row.get("project_id")
    if project_id is None or int(project_id) not in set(authorized_projects):
        return "project_unauthorized"
    if str(row.get("executor_surface") or "") not in NATIVE_TURN_RECORD_SURFACES:
        # Every other surface's turn end stamps itself, so a report about
        # one is evidence from the wrong place.
        return "surface_without_turn_record"
    if row.get("ended_at") or row.get("terminated_at"):
        return "session_terminal"
    return None


def _emit_observed(
    conn: Any,
    session_id: str,
    *,
    evidence: Mapping[str, Any],
    observed_at: str,
) -> None:
    from yoke_core.domain.events import emit_event

    emit_event(
        EVENT_SESSION_TURN_END_OBSERVED,
        event_kind="system",
        event_type="session_lifecycle",
        source_type="backend",
        session_id=session_id,
        context={
            "session_id": session_id,
            "observed_at": observed_at,
            "posture": NATIVE_TURN_END_POSTURE,
            "source": "relay_native_turn_record",
            **dict(evidence),
        },
        conn=conn,
    )


def apply_native_turn_ends(
    conn: Any,
    *,
    machine_id: str,
    authorized_projects: Iterable[int],
    reports: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Apply one machine's observed turn ends and name every refusal.

    Stamping is ordered against every other posture observation by the
    record's own timestamp, so a session that took a real turn after the
    error keeps the newer ``running`` and is left alone. Anything not
    applied comes back with a named status: a silent no-op here reads
    exactly like the stuck session this path exists to free.
    """
    current = now or utc_now()
    projects = tuple(sorted({int(value) for value in authorized_projects}))
    reclassified: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for report in reports:
        session_id = str(report.get("session_id") or "").strip()
        if not session_id:
            continue
        row = _session_row(conn, session_id)
        status = _skip_reason(row, machine_id=machine_id, authorized_projects=projects)
        if status is None:
            observed_at = str(report.get("observed_at") or "")
            stamped = stamp_turn_posture(
                conn,
                session_id=session_id,
                posture=NATIVE_TURN_END_POSTURE,
                observed_at=parse_timestamp(observed_at) or current,
            )
            if not stamped:
                # A newer posture observation already won, which means the
                # session took a turn after the record this report read.
                status = "posture_superseded"
            else:
                _emit_observed(
                    conn,
                    session_id,
                    evidence=report.get("evidence") or {},
                    observed_at=observed_at,
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
