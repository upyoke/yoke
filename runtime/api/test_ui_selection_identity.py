"""Browser preference identity follows the same operator as UI actions."""

from types import SimpleNamespace

from yoke_core.ui.local_operator_actor import local_selection_identity


def test_local_selection_identity_is_bound_to_universe_birth_and_actor(monkeypatch):
    from yoke_core.domain import db_helpers, session_actor_binding

    closed = []
    conn = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(db_helpers, "connect", lambda: conn)
    org = {"slug": "local", "created_at": "birth-a"}
    monkeypatch.setattr(db_helpers, "query_one", lambda *args: org)
    actor = SimpleNamespace(actor_id=3)
    monkeypatch.setattr(
        session_actor_binding, "resolve_operating_actor", lambda conn: actor
    )

    first = local_selection_identity()
    assert first["actorId"] == "3"
    org["created_at"] = "birth-b"
    assert local_selection_identity()["universeId"] != first["universeId"]
    actor.actor_id = None
    assert local_selection_identity() is None
    assert len(closed) == 3
