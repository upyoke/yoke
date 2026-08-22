"""HC-session-identity-provenance — detect invented session identity.

A session id is issued by the harness that owns the conversation and
resolved by every Yoke surface through the ambient chain (env stamp, then
the process-anchor ancestry registry). When that chain fails, the correct
outcome is the ``actor_session_missing`` refusal; inventing an id instead
produces a row that is indistinguishable from a real session on the board
while belonging to no conversation at all.

Two independent signatures of invented identity, each cheap enough to run
on every doctor pass:

* **Unrecognized surface label.** ``executor_surface`` is written from
  a closed vocabulary (:data:`yoke_contracts.executor_labels.KNOWN_EXECUTOR_LABELS`,
  plus ``NULL`` when the surface is unknown). A value outside it means the
  registering caller supplied free text rather than a detected surface.
* **Unregistered actor.** A session id that appears as an event actor but
  has no ``harness_sessions`` row acted without ever registering. Only
  UUID-shaped ids are considered: Yoke's service actors (sweeps, hosted
  UI, audits) are deliberately slug-named pseudo-sessions and are not
  harness conversations.

Both scans are bounded to live state — active sessions and a recent slice
of the event stream — so ended sessions and settled history stay quiet
without an exemption list to maintain. A finding here is about a writer
that is still producing bad identity, not about rows already on the board.

Verdicts:

* **PASS** — no active session carries an unrecognized label and no
  UUID-shaped actor is missing its row.
* **WARN** — at least one signature fired; the report names the session
  ids and the remediation.
* **SKIP** — ``harness_sessions`` is absent (minimal-schema fixture) or a
  scan query fails.
"""

from __future__ import annotations

import re
from typing import Any, List, Sequence, Tuple

from yoke_contracts.executor_labels import KNOWN_EXECUTOR_LABELS
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_SLUG = "HC-session-identity-provenance"
HC_LABEL = "Session identity is resolved, never invented"

#: Rows reported per signature before the listing is elided.
_MAX_REPORTED = 15
#: Ceiling on rows each scan may return, so one bad state cannot flood.
_MAX_SCANNED = 200
#: Recent event slice searched for actors with no session row. Bounded so
#: the check stays cheap on an event table that only ever grows.
_EVENT_SCAN_DEPTH = 20000

_UUID_PATTERN = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)

_LABEL_REMEDIATION = (
    "Fix the writer, not the row. A surface label reaches the database "
    "only through canonicalize_executor, which splits a detected executor "
    "into a canonical id plus a known alias — free text here means a "
    "caller supplied identity it did not detect. Add the surface to "
    "yoke_contracts.executor_labels.EXECUTOR_EMOJI when it is a real new "
    "surface; otherwise file a /yoke idea work item for the writer."
)

_ACTOR_REMEDIATION = (
    "These ids acted without a harness_sessions row, so their work is "
    "attributed to a session that was never registered. Two causes "
    "produce this. Either registration never happened — the harness "
    "hook's job at session start, so check that session's SessionStart "
    "hook delivery — or a resolver selected a child or otherwise "
    "unregistered id in place of the registered one, which is what a "
    "caller enumerating session env vars itself does instead of asking "
    "yoke_contracts.session_identity. Fix the writer either way; never "
    "register the id by hand."
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def scan_unknown_surface_labels(conn: Any) -> List[Tuple[str, Any, Any]]:
    """Return ``(session_id, executor_surface, offered_at)`` rows.

    Active sessions only, and only where the display name is present but
    outside the known vocabulary — ``NULL`` is the legitimate "surface not
    known" value, not an invented one.
    """
    p = _p(conn)
    placeholders = ",".join(p for _ in KNOWN_EXECUTOR_LABELS)
    sql = (
        "SELECT session_id, executor_surface, offered_at "
        "FROM harness_sessions "
        "WHERE ended_at IS NULL "
        "AND executor_surface IS NOT NULL "
        "AND executor_surface <> '' "
        f"AND executor_surface NOT IN ({placeholders}) "
        "ORDER BY offered_at DESC "
        f"LIMIT {_MAX_SCANNED}"
    )
    return list(conn.execute(sql, tuple(KNOWN_EXECUTOR_LABELS)).fetchall())


def scan_unregistered_actors(conn: Any) -> List[Tuple[str, Any, Any]]:
    """Return ``(session_id, event_count, last_seen)`` for unregistered actors.

    Restricted to UUID-shaped ids so Yoke's slug-named service actors stay
    out of the finding: they are pseudo-sessions by design and have no
    ``harness_sessions`` row to be missing.
    """
    sql = (
        "SELECT e.session_id, COUNT(*) AS event_count, "
        "MAX(e.created_at) AS last_seen "
        "FROM (SELECT session_id, created_at FROM events "
        f"ORDER BY id DESC LIMIT {_EVENT_SCAN_DEPTH}) e "
        "LEFT JOIN harness_sessions s ON s.session_id = e.session_id "
        "WHERE e.session_id IS NOT NULL AND e.session_id <> '' "
        "AND s.session_id IS NULL "
        "GROUP BY e.session_id "
        "ORDER BY event_count DESC "
        f"LIMIT {_MAX_SCANNED}"
    )
    rows = conn.execute(sql).fetchall()
    return [row for row in rows if _UUID_PATTERN.match(str(row[0]))]


def _render(header: str, lines: Sequence[str], remediation: str) -> List[str]:
    out: List[str] = [header]
    out.extend(lines[:_MAX_REPORTED])
    if len(lines) > _MAX_REPORTED:
        out.append(f"- ... +{len(lines) - _MAX_REPORTED} more")
    out.append("")
    out.append(remediation)
    return out


def hc_session_identity_provenance(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    if not _table_exists(conn, "harness_sessions"):
        rec.record(
            HC_SLUG, HC_LABEL, "SKIP",
            "harness_sessions table not present on this DB",
        )
        return

    try:
        unknown_labels = scan_unknown_surface_labels(conn)
    except db_backend.database_error_types(conn) as exc:
        rec.record(HC_SLUG, HC_LABEL, "SKIP", f"label scan failed: {exc}")
        return

    unregistered: List[Tuple[str, Any, Any]] = []
    if _table_exists(conn, "events"):
        try:
            unregistered = scan_unregistered_actors(conn)
        except db_backend.database_error_types(conn) as exc:
            rec.record(
                HC_SLUG, HC_LABEL, "SKIP", f"actor scan failed: {exc}",
            )
            return

    if not unknown_labels and not unregistered:
        rec.record(
            HC_SLUG, HC_LABEL, "PASS",
            "Every active session carries a known surface label "
            f"({', '.join(KNOWN_EXECUTOR_LABELS)} or NULL), and every "
            "UUID-shaped event actor has a harness_sessions row.",
        )
        return

    detail: List[str] = []
    if unknown_labels:
        detail.extend(_render(
            f"{len(unknown_labels)} active session(s) carry an "
            "unrecognized executor_surface:",
            [
                f"- session={sid!s} executor_surface={label!r} "
                f"offered_at={offered_at!s}"
                for sid, label, offered_at in unknown_labels
            ],
            _LABEL_REMEDIATION,
        ))
    if unregistered:
        if detail:
            detail.append("")
        detail.extend(_render(
            f"{len(unregistered)} UUID-shaped event actor(s) have no "
            f"harness_sessions row (last {_EVENT_SCAN_DEPTH} events):",
            [
                f"- session={sid!s} events={count!s} last_seen={last_seen!s}"
                for sid, count, last_seen in unregistered
            ],
            _ACTOR_REMEDIATION,
        ))
    rec.record(HC_SLUG, HC_LABEL, "WARN", "\n".join(detail))


__all__ = [
    "HC_LABEL",
    "HC_SLUG",
    "hc_session_identity_provenance",
    "scan_unknown_surface_labels",
    "scan_unregistered_actors",
]

from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        'session-identity-provenance',
        'Session identity is resolved, never invented',
        hc_session_identity_provenance,
    ),
)
