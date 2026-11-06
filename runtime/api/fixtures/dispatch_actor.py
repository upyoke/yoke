"""Give in-process test dispatch the actor production dispatch always carries.

The dispatcher refuses a side-effecting call that carries no numeric actor
(``actor_required``). Production calls get one from the bearer token, the
registered harness session, or the universe's operating actor. These helpers
model the same two shapes for tests:

* :func:`register_session_actor` registers a harness session bound to the
  universe's operating actor (holding org admin), so a test or a spawned
  engine that inherits ``YOKE_SESSION_ID`` dispatches as that actor through
  the real permission gate.
* :func:`authorize_every_dispatch` replaces the permission gate for unit
  suites that stub handlers and storage and exercise something other than
  authorization; it is the explicit opt-out those suites used to get
  implicitly from a non-numeric actor id.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from yoke_core.domain.yoke_function_permission_types import DispatchPermission


def register_session_actor(conn: Any, session_id: str) -> int:
    """Register ``session_id`` bound to the operating actor; return its id."""
    from yoke_core.domain.actors import seed_canonical_human
    from yoke_core.domain.org_schema import seed_default_org
    from runtime.api.fixtures.actor_roles import seed_org_role
    from runtime.api.fixtures.session_holdings import insert_session

    actor_id = seed_canonical_human(conn)
    seed_org_role(conn, actor_id=actor_id, org_id=seed_default_org(conn), role_name="owner")
    exists = conn.execute(
        "SELECT 1 FROM harness_sessions WHERE session_id = %s", (session_id,)
    ).fetchone()
    if exists is None:
        insert_session(conn, session_id)
    conn.execute(
        "UPDATE harness_sessions SET actor_id = %s WHERE session_id = %s",
        (actor_id, session_id),
    )
    conn.commit()
    return actor_id


def authorize_every_dispatch():
    """Patch the dispatcher's permission gate to authorize every call."""
    return patch(
        "yoke_core.domain.yoke_function_dispatch.dispatch_permission_for_request",
        lambda _entry, _request: DispatchPermission(None, None, None),
    )


__all__ = ["authorize_every_dispatch", "register_session_actor"]
