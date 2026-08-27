"""HC-session-actor-binding: sessions must name the actor they act for.

``harness_sessions.actor_id`` is bound at registration, and every write
that asks "who is doing this?" reads it — path-claim registration most
visibly, which refuses outright for a session that carries none. A row
written before actor binding existed keeps that NULL until something
re-registers it, and the operator only learns about it when a claim
refuses several steps later.

This check reads the rows directly and repairs them under ``--fix``,
binding each actor-less session to the actor that operates this
universe (:func:`yoke_core.domain.session_actor_binding.resolve_operating_actor`
— the same resolver registration uses, so a repaired row is
indistinguishable from a freshly registered one). When that actor cannot
be resolved, the check reports the resolver's own reason and recovery
rather than guessing at an identity.
"""

from __future__ import annotations

from typing import Any, List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.session_actor_binding import resolve_operating_actor

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


SLUG = "session-actor-binding"
TITLE = "Harness sessions carry the actor they act for"
_LISTED_SESSIONS = 5


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _actorless_session_ids(conn: Any) -> List[str]:
    rows = query_rows(
        conn,
        "SELECT session_id FROM harness_sessions "
        "WHERE actor_id IS NULL ORDER BY session_id",
    )
    return [
        str(row["session_id"] if isinstance(row, dict) else row[0])
        for row in rows
    ]


def _bind_sessions(conn: Any, actor_id: int) -> int:
    cursor = conn.execute(
        f"UPDATE harness_sessions SET actor_id = {_p(conn)} "
        "WHERE actor_id IS NULL",
        (actor_id,),
    )
    conn.commit()
    return int(getattr(cursor, "rowcount", 0) or 0)


def _summarize(session_ids: List[str]) -> str:
    shown = ", ".join(session_ids[:_LISTED_SESSIONS])
    remaining = len(session_ids) - _LISTED_SESSIONS
    return f"{shown} (+{remaining} more)" if remaining > 0 else shown


def hc_session_actor_binding(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Flag — and under ``--fix`` bind — sessions with no actor_id."""
    if not _base._table_exists(conn, "harness_sessions"):
        rec.record(
            SLUG, TITLE, "PASS", "harness_sessions table missing — nothing to check"
        )
        return

    actorless = _actorless_session_ids(conn)
    if not actorless:
        rec.record(SLUG, TITLE, "PASS", "every session row names an actor")
        return

    binding = resolve_operating_actor(conn)
    if not binding.bound:
        rec.record(
            SLUG,
            TITLE,
            "FAIL",
            f"{len(actorless)} session(s) carry no actor_id "
            f"({_summarize(actorless)}) and the operating actor cannot be "
            f"resolved to repair them: {binding.detail}",
        )
        return

    if args.fix:
        bound = _bind_sessions(conn, int(binding.actor_id))
        remaining = _actorless_session_ids(conn)
        if not remaining:
            rec.record(
                SLUG,
                TITLE,
                "PASS",
                f"--fix: bound {bound} session(s) to actor "
                f"{binding.actor_id} (this universe's operating actor)",
            )
            return
        actorless = remaining

    rec.record(
        SLUG,
        TITLE,
        "FAIL",
        f"{len(actorless)} session(s) carry no actor_id "
        f"({_summarize(actorless)}); those sessions cannot register a path "
        f"claim. Repair: `yoke doctor run --quick --fix`, which binds exactly "
        f"those rows to actor {binding.actor_id}, this universe's operating "
        "actor.",
    )


__all__ = ["SLUG", "TITLE", "hc_session_actor_binding"]
