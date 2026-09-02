"""Attribute a session-less mutating call to the actor that made it.

A function declared session-optional
(:mod:`yoke_core.domain.terminal_reachable_functions`) runs in a plain
terminal, where there is no harness session to read an actor from. It
still has an author: over https the bearer token names one before the
envelope reaches dispatch, and locally the universe knows who operates
it — the machine owner seeded at birth, holding org admin on the one org
(:mod:`yoke_core.domain.local_operating_actor`).

Binding that actor is what keeps a session-less write attributed rather
than anonymous, and it is the same resolution item creation already
performed for itself. Doing it once in the dispatcher's identity binder
makes it true of every session-optional function instead of the ones
that remembered — the difference between a contract and a patch.

Naming the actor is also what makes it answerable to the permission
gate, which enforces only once a numeric actor id is bound. A local
universe grants its machine owner org admin at birth, so the gate says
yes; a universe born before that grant existed converges it here, the
same repair session registration performs. Without that, binding an
actor on an older install would deny the very first terminal write, and
the operator would never learn that a missing role — not their command —
was the cause.

Best-effort by construction: resolution that cannot name an actor leaves
the request unbound and the call proceeds exactly as it did before. A
control plane reached over https has no local database to ask, and a
multi-person server has no single operating human to name; refusing
there would take out the merge subprocess and the relayed hook writes,
which have never carried an actor and do not need one. The handlers that
genuinely require an attributed actor refuse for themselves, naming the
binding refusal that :func:`resolve_operating_actor` already carries.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain import db_backend
from yoke_contracts.api.function_call import FunctionCallRequest


def operating_actor_id() -> Optional[str]:
    """Return this universe's operating actor id, or ``None``.

    ``None`` covers every miss the caller treats identically: no local
    control plane to ask (an https client), a database that cannot
    answer, or a universe whose operating actor is absent or ambiguous.
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
    except db_backend.operational_error_types():
        return None
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


__all__ = ["bind_operating_actor", "operating_actor_id"]
