"""Resolve the actor a harness session binds to when it registers.

Every session row names the actor it acts for, and that identity already
exists before any session registers: the local-universe birth path seeds
the machine owner's human actor, a self-hosted server seeds its admin
actor, and the hosted control plane verifies a bearer token. This module
answers the one question the registrar needs — "which actor operates this
universe?" — so registration binds that actor instead of storing NULL.

Resolution is deliberately narrow and fail-closed:

* an explicit actor (the verified bearer-token actor over https, or one
  an operator surface supplies) wins after a presence check;
* exactly one human actor on the authority — that actor;
* several humans — the single human whose ``actor_labels`` row matches
  the calling process's OS login, the label the local-universe birth
  path seeds for the machine owner;
* anything else — a named refusal carrying its recovery command.

Why refuse instead of storing NULL: an actor-less session looks healthy
until the first path-claim registration, which refuses far away from the
registration that caused it. A fresh install proved that failure mode —
no session on it ever bound an actor, so no item could reach a worktree,
and nothing on the install named the missing binding as the cause.

:func:`resolve_operating_actor` takes an open control-plane connection so
both callers share one answer: session registration
(:mod:`yoke_core.domain.sessions_lifecycle_identity`) and the loopback UI,
which needs the same "who operates this machine?" resolution for
actor-scoped writes.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Any, List, Optional

from yoke_core.domain import db_backend


#: Refusal codes. Uppercase because :class:`SessionError` codes are the
#: surface operators and the function dispatcher both read.
ACTOR_MISSING = "SESSION_ACTOR_MISSING"
ACTOR_AMBIGUOUS = "SESSION_ACTOR_AMBIGUOUS"
ACTOR_IDENTITY_UNAVAILABLE = "SESSION_ACTOR_IDENTITY_UNAVAILABLE"
ACTOR_INVALID = "SESSION_ACTOR_INVALID"


@dataclass(frozen=True)
class ActorBinding:
    """A resolved actor, or a named refusal with its recovery step."""

    actor_id: Optional[int] = None
    code: str = ""
    detail: str = ""

    @property
    def bound(self) -> bool:
        return self.actor_id is not None


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def os_login() -> str:
    """Return this process's OS login, or "" when it cannot be read."""
    try:
        return (getpass.getuser() or "").strip()
    except Exception:  # noqa: BLE001 — a missing login is a resolution miss
        return ""


def _human_actor_ids(conn: Any) -> Optional[List[int]]:
    """Human actor ids, or ``None`` when the authority has no actors table."""
    try:
        rows = conn.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        _rollback_quietly(conn)
        return None
    return [int(row[0]) for row in rows]


def _actor_ids_for_label(conn: Any, label: str) -> List[int]:
    try:
        rows = conn.execute(
            "SELECT DISTINCT al.actor_id FROM actor_labels al "
            "JOIN actors a ON a.id = al.actor_id "
            f"WHERE a.kind = 'human' AND al.label = {_p(conn)}",
            (label,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        _rollback_quietly(conn)
        return []
    return [int(row[0]) for row in rows]


def _rollback_quietly(conn: Any) -> None:
    """Clear the aborted-transaction state a failed probe leaves on Postgres."""
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 — the probe result is the whole product
        pass


def explicit_actor_binding(conn: Any, actor_id: Any) -> ActorBinding:
    """Bind an explicitly supplied actor, or refuse naming why."""
    try:
        candidate = int(actor_id)
    except (TypeError, ValueError):
        return ActorBinding(
            code=ACTOR_INVALID,
            detail=(
                f"actor_id {actor_id!r} is not an integer, so no session "
                "identity can be bound. Recovery: pass the numeric actor id "
                "(`yoke db read \"SELECT id, kind FROM actors\"`), or omit it "
                "to bind this universe's operating actor."
            ),
        )
    from yoke_core.domain.actors import validate_actor_id

    try:
        present = validate_actor_id(conn, candidate)
    except db_backend.operational_error_types(conn):
        _rollback_quietly(conn)
        return _identity_unavailable()
    if present:
        return ActorBinding(actor_id=candidate)
    return ActorBinding(
        code=ACTOR_INVALID,
        detail=(
            f"actor_id {candidate} does not exist on this control plane, so "
            "no session identity can be bound. Recovery: pass an actor this "
            "authority carries (`yoke db read \"SELECT id, kind FROM "
            "actors\"`), or omit it to bind this universe's operating actor."
        ),
    )


def _identity_unavailable() -> ActorBinding:
    return ActorBinding(
        code=ACTOR_IDENTITY_UNAVAILABLE,
        detail=(
            "this control plane has no readable actors table, so no session "
            "identity can be bound. Recovery: bring the database up to the "
            "build serving it — a server converges its schema on boot; run "
            "`yoke doctor run --quick` on a local universe — then retry."
        ),
    )


def resolve_operating_actor(conn: Any) -> ActorBinding:
    """Return the actor that operates this universe, or a named refusal."""
    humans = _human_actor_ids(conn)
    if humans is None:
        return _identity_unavailable()
    if len(humans) == 1:
        return ActorBinding(actor_id=humans[0])
    if not humans:
        return ActorBinding(
            code=ACTOR_MISSING,
            detail=(
                "this control plane carries no human actor, so a registering "
                "session has no identity to bind (and could not register a "
                "path claim later). Recovery: run `yoke onboard` on this "
                "machine — its universe step seeds the operating human "
                "actor — then retry."
            ),
        )
    login = os_login()
    matches = _actor_ids_for_label(conn, login) if login else []
    if len(matches) == 1:
        return ActorBinding(actor_id=matches[0])
    listed = ", ".join(str(actor_id) for actor_id in humans)
    return ActorBinding(
        code=ACTOR_AMBIGUOUS,
        detail=(
            f"this control plane carries {len(humans)} human actors "
            f"({listed}) and none is labeled with this machine's login "
            f"{login or '(unreadable)'!r}, so the operating actor is "
            "ambiguous. Recovery: connect this machine to the server that "
            "owns those identities (`yoke onboard --connect URL`) so the "
            "verified token binds your actor."
        ),
    )


__all__ = [
    "ACTOR_AMBIGUOUS",
    "ACTOR_IDENTITY_UNAVAILABLE",
    "ACTOR_INVALID",
    "ACTOR_MISSING",
    "ActorBinding",
    "explicit_actor_binding",
    "os_login",
    "resolve_operating_actor",
]
