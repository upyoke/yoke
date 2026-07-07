"""Unit tests for the actor-id resolution path in ``backlog_create_op``.

``items.source`` and ``items.owner`` are stringified ``actors.id``
values. Actor identity is session/auth-bound: with no explicit
``source`` the writer resolves the calling session's
``harness_sessions.actor_id``; there is no machine-default actor. The
writer validates any explicit ``source`` argument against the
``actors`` table — mechanism labels like ``user``, ``bug``, or
``simulation`` are not accepted.

These tests target the helper-and-coercion surface directly so the
write contract is covered without booting the full ``execute_create``
mutation path.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from yoke_core.domain.actors import (
    GITHUB_LABEL_SURFACE,
    seed_canonical_actors,
    seed_human_actor,
    set_actor_label,
)  # noqa: F401  (set_actor_label / GITHUB_LABEL_SURFACE used by secondary-human test)
from yoke_core.domain.backlog_create_op import (
    SourceActorResolutionError,
    _coerce_explicit_source,
    _resolve_session_source_actor,
)
from yoke_core.domain.db_helpers import iso8601_now


@pytest.fixture
def seeded_conn(test_db: Any) -> Any:
    """``test_db`` already seeds canonical actors; alias for readability."""
    return test_db


@pytest.fixture(autouse=True)
def _no_ambient_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the ambient-session rung off so only explicit ids resolve."""
    monkeypatch.setattr(
        "yoke_core.domain.path_claims_actor_resolution._current_session_id",
        lambda: "",
    )


def _seed_session(conn: Any, session_id: str, actor_id: Optional[int]) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "workspace, offered_at, last_heartbeat, actor_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (session_id, "claude-code", "anthropic", "test-model", "/tmp/ws",
         now, now, actor_id),
    )


class TestResolveSessionSourceActor:
    def test_session_bound_actor_resolves(self, seeded_conn):
        yoke_core, _ = seed_canonical_actors(seeded_conn)
        _seed_session(seeded_conn, "sess-src-bound", yoke_core)
        assert _resolve_session_source_actor(
            seeded_conn, "sess-src-bound",
        ) == yoke_core

    def test_session_without_actor_fails_closed(self, seeded_conn):
        _seed_session(seeded_conn, "sess-src-null", None)
        with pytest.raises(
            SourceActorResolutionError, match="no bound actor"
        ):
            _resolve_session_source_actor(seeded_conn, "sess-src-null")

    def test_no_session_fails_closed(self, seeded_conn):
        with pytest.raises(
            SourceActorResolutionError, match="--source"
        ):
            _resolve_session_source_actor(seeded_conn, None)


class TestCoerceExplicitSource:
    def test_numeric_id_for_existing_actor_passes(self, seeded_conn):
        _, local_human = seed_canonical_actors(seeded_conn)
        assert _coerce_explicit_source(seeded_conn, str(local_human)) == local_human

    def test_mechanism_label_rejected(self, seeded_conn):
        for token in ("user", "bug", "simulation", "ben"):
            with pytest.raises(
                SourceActorResolutionError,
                match="must be a numeric actor id",
            ):
                _coerce_explicit_source(seeded_conn, token)

    def test_unknown_numeric_id_rejected(self, seeded_conn):
        with pytest.raises(
            SourceActorResolutionError, match="does not match any actors row"
        ):
            _coerce_explicit_source(seeded_conn, "424242")

    def test_secondary_human_actor_resolves(self, seeded_conn):
        # Two humans, distinct labels — the writer must accept either id
        # without conflating them.
        secondary = seed_human_actor(seeded_conn)
        set_actor_label(
            seeded_conn,
            secondary,
            "alice",
            surface=GITHUB_LABEL_SURFACE,
        )
        assert _coerce_explicit_source(seeded_conn, str(secondary)) == secondary
