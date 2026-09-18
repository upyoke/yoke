"""Transport boundary for client-local agent rendering metadata."""

from __future__ import annotations

from unittest.mock import Mock

from yoke_core.domain import agents_render_path_context as subject
from yoke_core.domain.function_authz_scope import classify
from yoke_core.domain.function_authz_types import ACTOR_SESSION


def test_relationship_refresh_is_actor_session_scoped():
    spec = classify(
        "agents.render_relationships.record",
        side_effects=True,
        project_permission=None,
    )

    assert spec.scope == ACTOR_SESSION
    assert spec.permission_key is None


def test_relationship_refresh_relays_when_no_local_authority(monkeypatch):
    relay = Mock(return_value={"written": 14})
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        lambda _connect: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        relay,
    )

    written = subject.record_render_relationships_to_canonical_db(
        session_id="session-1"
    )

    assert written == 14
    relay.assert_called_once_with(
        "agents.render_relationships.record",
        {"session_id": "session-1"},
    )


def test_relationship_refresh_keeps_file_render_advisory(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        lambda _connect: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        Mock(side_effect=RuntimeError("authority unavailable")),
    )

    assert subject.record_render_relationships_to_canonical_db() == 0


def test_record_render_relationships_looks_up_paths_in_one_query(tmp_path):
    from runtime.api.domain.test_path_context import _seed_target
    from runtime.api.path_context_test_helpers import init_minimal_schema
    from yoke_core.domain.agents_render_path_context import (
        record_render_relationships,
    )
    from yoke_core.domain.render_relationship_inventory import (
        render_relationship_map,
    )

    conn = init_minimal_schema(str(tmp_path / "t.db"))
    try:
        relationships = render_relationship_map()
        for target_path in relationships:
            _seed_target(conn, path_string=target_path)
        conn.commit()
        original = conn.execute
        lookups = {"n": 0}

        def counting(sql, params=None):
            text = str(sql)
            if "FROM path_targets" in text and "path_string IN" in text:
                lookups["n"] += 1
            if params is None:
                return original(sql)
            return original(sql, params)

        conn.execute = counting  # type: ignore[method-assign]
        written = record_render_relationships(conn)
        assert written == len(relationships)
        assert lookups["n"] == 1
    finally:
        conn.close()
