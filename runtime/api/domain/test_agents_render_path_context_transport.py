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
