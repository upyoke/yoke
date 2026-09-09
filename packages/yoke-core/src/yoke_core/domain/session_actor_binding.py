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
* otherwise the actor id this machine recorded for the connection it is
  using, verified to still exist and PROVEN to belong to the same
  universe it was recorded against — an unstated universe on either side
  refuses rather than passing;
* anything else — a named refusal carrying its recovery command.

There is no name-matching rung and no "well, there is only one human"
rung. Both are guesses, and a guess about identity is the kind of bug
that stays invisible until it has attributed somebody's work to somebody
else. A person's OS login is not their identity in a universe; a name is
not unique, is not stable, and is owned by whatever account system
supplies it. So the binding is written once, explicitly, by the paths
that already know the answer — universe birth, universe import, and the
doctor repair — and read back by id afterwards (those writers live in
:mod:`yoke_core.domain.session_actor_binding_write`). Renaming an actor
cannot move it, and two people who share a name stay two bindings.

The recorded binding names the universe as well as the actor, because an
env label is a machine-local nickname that can be re-pointed at another
control plane. Verifying the universe is what makes a retarget a refusal
instead of a silent binding to whoever holds that id over there.

Why refuse instead of storing NULL: an actor-less session looks healthy
until the first path-claim registration, which refuses far away from the
registration that caused it. A fresh install proved that failure mode —
no session on it ever bound an actor, so no item could reach a worktree,
and nothing on the install named the missing binding as the cause.

:func:`resolve_operating_actor` takes an open control-plane connection so
every caller shares one answer: session registration
(:mod:`yoke_core.domain.sessions_lifecycle_identity`), the loopback UI,
and the session-less terminal binder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema_connections import (
    operating_actor_binding,
)
from yoke_core.domain import db_backend
from yoke_core.domain.universe_identity import universe_fingerprint


#: Refusal codes. Uppercase because :class:`SessionError` codes are the
#: surface operators and the function dispatcher both read.
ACTOR_MISSING = "SESSION_ACTOR_MISSING"
ACTOR_UNBOUND = "SESSION_ACTOR_UNBOUND"
ACTOR_UNIVERSE_MISMATCH = "SESSION_ACTOR_UNIVERSE_MISMATCH"
ACTOR_UNIVERSE_UNPROVEN = "SESSION_ACTOR_UNIVERSE_UNPROVEN"
ACTOR_IDENTITY_UNAVAILABLE = "SESSION_ACTOR_IDENTITY_UNAVAILABLE"
ACTOR_INVALID = "SESSION_ACTOR_INVALID"

#: The one command that records a machine's operating-actor binding.
OPERATING_ACTOR_BIND_COMMAND = "yoke config bind-actor --actor-id <id>"

#: How to see the candidates that command chooses between.
OPERATING_ACTOR_LIST_COMMAND = 'yoke db read "SELECT id, kind, name FROM actors"'


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


def _rollback_quietly(conn: Any) -> None:
    """Clear the aborted-transaction state a failed probe leaves on Postgres."""
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 — the probe result is the whole product
        pass


def _actors_readable(conn: Any) -> bool:
    try:
        conn.execute("SELECT 1 FROM actors LIMIT 1").fetchone()
    except db_backend.operational_error_types(conn):
        _rollback_quietly(conn)
        return False
    return True


def _human_actor_count(conn: Any) -> int:
    rows = conn.execute("SELECT id FROM actors WHERE kind = 'human'").fetchall()
    return len(rows)


def _selected_env(env: Optional[str], config_path: Any) -> str:
    if env:
        return str(env).strip()
    try:
        return machine_config.active_env(config_path)
    except Exception:  # noqa: BLE001 — an unresolvable env is an unbound machine
        return ""


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
                f"(`{OPERATING_ACTOR_LIST_COMMAND}`), or omit it to bind "
                "this universe's operating actor."
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
            f"authority carries (`{OPERATING_ACTOR_LIST_COMMAND}`), or omit "
            "it to bind this universe's operating actor."
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


def resolve_operating_actor(
    conn: Any,
    *,
    env: Optional[str] = None,
    config_path: Any = None,
) -> ActorBinding:
    """Return the actor that operates this universe, or a named refusal."""
    if not _actors_readable(conn):
        return _identity_unavailable()
    if _human_actor_count(conn) == 0:
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

    selected = _selected_env(env, config_path)
    try:
        payload = machine_config.load_config(config_path)
    except Exception:  # noqa: BLE001 — an unreadable config is an unbound machine
        payload = {}
    actor_id, recorded_universe = operating_actor_binding(payload, selected)
    if actor_id is None:
        return ActorBinding(
            code=ACTOR_UNBOUND,
            detail=(
                "this machine has recorded no operating actor for connection "
                f"{selected or '(unresolved)'!r}, so a registering session has "
                "no identity to bind. Over https a verified bearer token names "
                "your actor instead; on a directly connected universe, record "
                f"it once with `{OPERATING_ACTOR_BIND_COMMAND}` "
                f"(`{OPERATING_ACTOR_LIST_COMMAND}` lists the candidates)."
            ),
        )

    # Same-universe has to be PROVEN, not merely "not contradicted". A
    # missing fingerprint on either side is an unanswered question, and
    # accepting the id anyway is exactly the retarget this check exists to
    # catch — an env label re-pointed at another control plane produces a
    # recorded id whose universe nobody can vouch for.
    live_universe = universe_fingerprint(conn)
    if not recorded_universe:
        return ActorBinding(
            code=ACTOR_UNIVERSE_UNPROVEN,
            detail=(
                f"the operating actor recorded for connection {selected!r} "
                "names no universe, so there is no proof actor "
                f"{actor_id} belongs to the one this connection reaches. "
                "Recovery: re-record the binding against this universe with "
                f"`{OPERATING_ACTOR_BIND_COMMAND}`."
            ),
        )
    if not live_universe:
        return ActorBinding(
            code=ACTOR_UNIVERSE_UNPROVEN,
            detail=(
                f"this control plane does not answer for its own identity "
                "(a universe carries exactly one organization identity card, "
                "and this one carries none or several), so the operating "
                f"actor recorded for connection {selected!r} cannot be proven "
                "to belong to it. Recovery: bring the universe to one "
                "organization — `yoke doctor run --quick` reports the shape — "
                "then retry."
            ),
        )
    if recorded_universe != live_universe:
        return ActorBinding(
            code=ACTOR_UNIVERSE_MISMATCH,
            detail=(
                f"connection {selected!r} now reaches a different universe "
                f"({live_universe}) than the one its recorded operating actor "
                f"belongs to ({recorded_universe}), so actor {actor_id} may "
                "name a different person here. Recovery: re-record the "
                f"binding for this universe with `{OPERATING_ACTOR_BIND_COMMAND}`."
            ),
        )

    binding = explicit_actor_binding(conn, actor_id)
    if binding.bound:
        return binding
    return ActorBinding(
        code=ACTOR_UNBOUND,
        detail=(
            f"this machine's recorded operating actor for connection "
            f"{selected!r} is actor {actor_id}, which this control plane no "
            "longer carries. Recovery: re-record the binding with "
            f"`{OPERATING_ACTOR_BIND_COMMAND}` "
            f"(`{OPERATING_ACTOR_LIST_COMMAND}` lists the candidates)."
        ),
    )


__all__ = [
    "ACTOR_IDENTITY_UNAVAILABLE",
    "ACTOR_INVALID",
    "ACTOR_MISSING",
    "ACTOR_UNBOUND",
    "ACTOR_UNIVERSE_MISMATCH",
    "ACTOR_UNIVERSE_UNPROVEN",
    "ActorBinding",
    "OPERATING_ACTOR_BIND_COMMAND",
    "OPERATING_ACTOR_LIST_COMMAND",
    "explicit_actor_binding",
    "resolve_operating_actor",
]
