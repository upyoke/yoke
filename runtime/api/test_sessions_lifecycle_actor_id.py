# ruff: noqa: F811  (the shared `conn` fixture is imported, then used by name)
"""``register_session`` actor-binding coverage.

Split out of ``test_sessions_lifecycle.py`` once the parent file crossed
the 350-line gate. Registration binds the actor a session acts for: an
explicitly supplied one (the verified bearer-token actor over https)
wins, and otherwise the universe's operating actor is resolved, because
that identity already exists before any session registers. Nothing falls
through to NULL — an actor-less session cannot register a path claim, so
registration refuses with a named reason and a recovery step instead.

The cases cover the explicit / implicit / valid / unresolvable matrix:

* explicit-and-valid -> stored
* explicit-and-unknown -> refused (SESSION_ACTOR_INVALID)
* implicit + a recorded operating actor -> that actor, by id
* implicit + several humans sharing a name -> still the recorded id
* implicit + no recorded binding -> refused (SESSION_ACTOR_UNBOUND)
* implicit + no human actor -> refused (SESSION_ACTOR_MISSING)
* re-registration of a row that predates binding -> backfilled

The shared `conn` fixture and `_register` helper come from the sibling
test_sessions module, whose schema carries the `actors` table and seeds
the one human actor every born universe has. ``machine_config`` pins a
throwaway config file so the implicit rung reads this test's binding
rather than the operator's own machine.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.sessions import SessionError
from runtime.api.test_sessions import (
    conn,  # noqa: F401  (pytest fixture)
    _register,
)

ENV = "local"


@pytest.fixture(autouse=True)
def machine_config(tmp_path, monkeypatch):
    """A throwaway machine config, so no test reads the operator's own."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "active_env": ENV,
                "connections": {ENV: {"transport": "local-postgres"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(path))
    return path


def _bind(conn, actor_id: int) -> None:
    from yoke_core.domain.session_actor_binding_write import persist_operating_actor

    persist_operating_actor(conn, actor_id, env=ENV)


def _forget_the_binding(config_path) -> None:
    """Return this machine to never having recorded an operating actor."""
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["connections"] = {
        env: {key: value for key, value in entry.items() if key != "operating_actor"}
        for env, entry in (payload.get("connections") or {}).items()
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")


def _stored_actor_id(db, session_id: str):
    return db.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()["actor_id"]


def _seeded_human_id(db) -> int:
    return int(
        db.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


def _drop_human_actors(db) -> None:
    db.execute("DELETE FROM actors WHERE kind = 'human'")
    db.commit()


class TestRegisterSessionActorId:
    def test_register_persists_explicit_actor_id(self, conn):
        from yoke_core.domain.actors import seed_human_actor

        actor_id = seed_human_actor(conn)
        _register(conn, session_id="sess-actor-explicit", actor_id=actor_id)
        assert _stored_actor_id(conn, "sess-actor-explicit") == actor_id

    def test_register_refuses_unknown_explicit_actor_id(self, conn):
        """A stale numeric id is named, not silently dropped to NULL: the
        caller asked for an identity this authority does not carry."""
        with pytest.raises(SessionError) as excinfo:
            _register(conn, session_id="sess-actor-bad", actor_id=424242)
        assert excinfo.value.code == "SESSION_ACTOR_INVALID"
        assert "424242" in excinfo.value.message
        assert conn.execute(
            "SELECT COUNT(*) FROM harness_sessions WHERE session_id = %s",
            ("sess-actor-bad",),
        ).fetchone()[0] == 0

    def test_register_binds_the_recorded_operating_actor(self, conn):
        """The fresh-install case: nobody passes an actor, and the row still
        names the human the install recorded itself as operating."""
        _bind(conn, _seeded_human_id(conn))
        _register(conn, session_id="sess-actor-implicit")
        assert _stored_actor_id(conn, "sess-actor-implicit") == _seeded_human_id(conn)

    def test_register_binds_by_id_even_when_two_humans_share_a_name(self, conn):
        """Names are not identities, so a namesake cannot take the binding."""
        from yoke_core.domain.actors import seed_human_actor, set_actor_name

        bound = _seeded_human_id(conn)
        set_actor_name(conn, bound, "Ada Lovelace")
        namesake = seed_human_actor(conn, "Ada Lovelace")
        _bind(conn, bound)

        _register(conn, session_id="sess-actor-namesake")

        stored = _stored_actor_id(conn, "sess-actor-namesake")
        assert stored == bound
        assert stored != namesake

    def test_register_refuses_when_no_operating_actor_is_recorded(
        self, conn, machine_config,
    ):
        """No binding is an unanswered question, not an invitation to guess."""
        _forget_the_binding(machine_config)
        with pytest.raises(SessionError) as excinfo:
            _register(conn, session_id="sess-actor-unbound")
        assert excinfo.value.code == "SESSION_ACTOR_UNBOUND"
        assert "yoke config bind-actor" in excinfo.value.message

    def test_register_refuses_when_no_human_actor_exists(self, conn):
        """The unresolvable case names the reason and the recovery instead of
        writing the NULL that only surfaces at the first path claim."""
        _drop_human_actors(conn)
        with pytest.raises(SessionError) as excinfo:
            _register(conn, session_id="sess-actor-none")
        assert excinfo.value.code == "SESSION_ACTOR_MISSING"
        assert "yoke onboard" in excinfo.value.message

    def test_reregistration_backfills_a_row_that_predates_binding(self, conn):
        """Rows written before binding existed heal on the next registration
        probe — the same path the hook chain drives on every session."""
        _bind(conn, _seeded_human_id(conn))
        _register(conn, session_id="sess-actor-legacy")
        conn.execute(
            "UPDATE harness_sessions SET actor_id = NULL WHERE session_id = %s",
            ("sess-actor-legacy",),
        )
        conn.commit()
        with pytest.raises(SessionError) as excinfo:
            _register(conn, session_id="sess-actor-legacy")
        assert excinfo.value.code == "SESSION_EXISTS"
        assert _stored_actor_id(conn, "sess-actor-legacy") == _seeded_human_id(conn)
