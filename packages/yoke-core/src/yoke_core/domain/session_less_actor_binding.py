"""Attribute an actor-less call to the actor that operates this universe.

A mutating call can reach in-process dispatch with no actor: a
session-optional function
(:mod:`yoke_core.domain.terminal_reachable_functions`) run in a plain
terminal, or a call whose session has no ``harness_sessions`` row or no
actor on it. It still has an author: over https the bearer token names
one before the envelope reaches dispatch, and locally the universe knows
who operates it — the machine owner seeded at birth, holding org admin on
the one org (:mod:`yoke_core.domain.local_operating_actor`).

Binding that actor is what keeps the write attributed rather than
anonymous. Doing it once in the dispatcher's identity binder makes it
true of every mutating function instead of the ones that remembered. A
read answered for its viewer (actor-session or org scope, such as pending
machine approvals or teammate invites) binds the same actor, so a local
universe's plain terminal gets the read's own answer instead of
``actor_required``.

Naming the actor is also what makes the call answerable to the permission
gate, which refuses a side-effecting call with no numeric actor
(``actor_required``, :mod:`yoke_core.domain.dispatch_actor_requirement`).
A local universe grants its machine owner org admin at birth, so the gate
says yes; a universe born before that grant existed converges it here,
the same repair session registration performs.

Resolution that cannot name an actor leaves the request unbound, and the
gate then refuses it with the recovery: run from a registered harness
session, run ``yoke setup`` so the machine records its operating actor, or
connect over https. A multi-person server has no single operating human
to name; its callers arrive over https already carrying their bearer actor.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.yoke_function_registry import RegistryEntry


def operating_actor_id() -> Optional[str]:
    """Resolve once within a deploy driver's identity scope."""
    from yoke_core.domain.deployment_driver_identity import identity_read

    return identity_read("operating_actor", _load_operating_actor_id)


def _load_operating_actor_id() -> Optional[str]:
    """Return this universe's operating actor id, or ``None``.

    ``None`` means no local authority or an absent/ambiguous operating actor.
    A database error propagates so binding reports connection loss.
    """
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.control_plane_transport import (
            local_connection_or_none,
        )
        from yoke_core.domain.local_operating_actor import (
            converge_operating_actor_grant,
        )
        from yoke_core.domain.session_actor_binding import (
            resolve_operating_actor,
        )
    except Exception:  # noqa: BLE001 — import-time miss is a resolution miss
        return None
    conn = local_connection_or_none(db_helpers.connect)
    if conn is None:
        return None
    try:
        binding = resolve_operating_actor(conn)
        if binding.actor_id is not None and converge_operating_actor_grant(conn):
            conn.commit()
    except (AttributeError, RuntimeError, TypeError):
        return None
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — the resolution is the whole product
            pass
    return None if binding.actor_id is None else str(binding.actor_id)


def bind_operating_actor(request: FunctionCallRequest) -> FunctionCallRequest:
    """Return ``request`` carrying the operating actor when it carries none.

    An actor the envelope already names wins untouched: over https that
    is the bearer-token actor the boundary verified, and an operator
    debugging with an explicit actor means the one they passed.
    """
    if (request.actor.actor_id or "").strip():
        return request
    actor_id = operating_actor_id()
    if not actor_id:
        return request
    actor = request.actor.model_copy(update={"actor_id": actor_id})
    return request.model_copy(update={"actor": actor})


def needs_operating_actor(entry: RegistryEntry, *, read_only: bool) -> bool:
    """Whether an actor-less call to *entry* is answered for a person.

    Writes need an author. A read scoped to its viewer (the caller's own
    session or their org) needs one too: without it a local universe's
    plain terminal could not even learn that the read does not apply here.
    """
    if not read_only:
        return True
    from yoke_core.domain.function_authz_scope import classify, permission_key_for
    from yoke_core.domain.function_authz_types import ACTOR_SESSION, ORG

    spec = classify(
        entry.function_id,
        side_effects=bool(entry.side_effects),
        project_permission=permission_key_for(entry),
    )
    return spec.scope in (ACTOR_SESSION, ORG)


def bind_operating_actor_if_needed(
    entry: RegistryEntry, request: FunctionCallRequest, *, read_only: bool
) -> FunctionCallRequest:
    """Bind the operating actor when :func:`needs_operating_actor` says so."""
    if needs_operating_actor(entry, read_only=read_only):
        return bind_operating_actor(request)
    return request


__all__ = [
    "bind_operating_actor",
    "bind_operating_actor_if_needed",
    "needs_operating_actor",
    "operating_actor_id",
]
