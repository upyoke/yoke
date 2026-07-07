"""``register_session`` actor_id coverage.

Split out of ``test_sessions_lifecycle.py`` once the parent file
crossed the 350-line gate. Actor identity is session/auth-bound:
callers that know the actor pass it explicitly; without one the row
stores NULL — there is no machine-default actor rung. The cases cover
the explicit / implicit / valid / invalid matrix on the actor_id
keyword:

* explicit-and-valid -> stored
* explicit-and-invalid -> stored as NULL (validate-and-fallback)
* implicit + unseeded fixture -> stored as NULL
* implicit + seeded canonical actors -> still NULL (no implicit rung)

The shared `conn` fixture and `_register` helper come from the
sibling test_sessions module so the schema (with `actors` and
`actor_labels` tables) and registration default kwargs match the
parent suite.
"""

from __future__ import annotations

from runtime.api.test_sessions import (
    conn,  # noqa: F401  (pytest fixture)
    _register,
)


class TestRegisterSessionActorId:
    def test_register_persists_explicit_actor_id(self, conn):
        from yoke_core.domain.actors import seed_human_actor

        actor_id = seed_human_actor(conn)
        _register(conn, session_id="sess-actor-explicit", actor_id=actor_id)
        stored = conn.execute(
            "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
            ("sess-actor-explicit",),
        ).fetchone()["actor_id"]
        assert stored == actor_id

    def test_register_skips_invalid_explicit_actor_id(self, conn):
        """A stale numeric id falls back to NULL rather than poisoning
        the column — mirrors the writer-side `_coerce_explicit_source`
        policy without aborting session-begin. The operator can amend
        later via the lifecycle helpers."""
        _register(conn, session_id="sess-actor-bad", actor_id=424242)
        stored = conn.execute(
            "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
            ("sess-actor-bad",),
        ).fetchone()["actor_id"]
        assert stored is None

    def test_register_without_actor_stores_null(self, conn):
        """Without an explicit actor the session row stores NULL rather
        than aborting session-begin."""
        _register(conn, session_id="sess-actor-default")
        stored = conn.execute(
            "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
            ("sess-actor-default",),
        ).fetchone()["actor_id"]
        assert stored is None

    def test_register_implicit_stays_null_even_with_seeded_actors(self, conn):
        """Seeded canonical actors do NOT implicitly bind: actor identity
        comes from the caller (token boundary, operator tooling), never
        from an ambient default."""
        from yoke_core.domain.actors import seed_canonical_actors

        seed_canonical_actors(conn)
        _register(conn, session_id="sess-actor-implicit")
        stored = conn.execute(
            "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
            ("sess-actor-implicit",),
        ).fetchone()["actor_id"]
        assert stored is None
