"""Tests for actor seeding, resolution, and central label rendering."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_display import actor_display_name
from yoke_core.domain.actors import (
    ActorLabelAmbiguous,
    ActorLabelMissing,
    ActorNotFound,
    DISPLAY_LABEL_SURFACE,
    GITHUB_LABEL_SURFACE,
    SYSTEM_COMPONENT_YOKE_CORE,
    actor_label,
    actor_label_or_passthrough,
    labels_for_surface,
    resolve_actor_by_label,
    seed_human_actor,
    seed_system_actor,
    set_actor_label,
    validate_actor_id,
)
from yoke_core.domain.actor_render import actor_render_label
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_seed_system_actor_is_idempotent(conn):
    a = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    b = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    assert a == b
    rows = conn.execute(
        "SELECT COUNT(*) FROM actors WHERE system_component = %s",
        (SYSTEM_COMPONENT_YOKE_CORE,),
    ).fetchone()
    assert rows[0] == 1


def test_seed_human_actor_creates_distinct_rows(conn):
    a = seed_human_actor(conn)
    b = seed_human_actor(conn)
    assert a != b


def test_seed_canonical_actors_label_resolution_precedence(conn, monkeypatch):
    from yoke_core.domain.actors import (
        DEFAULT_LOCAL_HUMAN_LABEL,
        LOCAL_HUMAN_LABEL_ENV,
        seed_canonical_actors,
    )

    monkeypatch.delenv(LOCAL_HUMAN_LABEL_ENV, raising=False)
    _, default_human = seed_canonical_actors(conn)
    assert resolve_actor_by_label(conn, DEFAULT_LOCAL_HUMAN_LABEL) == default_human

    # The env injection (how the no-argument init chain passes the
    # universe owner's login through) names the human actor.
    monkeypatch.setenv(LOCAL_HUMAN_LABEL_ENV, "env-owner")
    _, env_human = seed_canonical_actors(conn)
    assert env_human != default_human
    assert resolve_actor_by_label(conn, "env-owner") == env_human

    # An explicit argument beats the env injection.
    monkeypatch.setenv(LOCAL_HUMAN_LABEL_ENV, "env-owner")
    _, explicit_human = seed_canonical_actors(
        conn, local_human_label="explicit-owner"
    )
    assert resolve_actor_by_label(conn, "explicit-owner") == explicit_human

    # Idempotent per label: the same injection resolves the existing
    # actor instead of duplicating it.
    _, again = seed_canonical_actors(conn)
    assert again == env_human


def test_actor_render_label_is_fail_open_for_display(conn):
    # Human actor with a label resolves to that label.
    human = seed_human_actor(conn)
    set_actor_label(conn, human, "ben")
    assert actor_render_label(conn, human) == "ben"
    # System actor renders its component (the actor_label system path).
    system = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    assert actor_render_label(conn, system) == SYSTEM_COMPONENT_YOKE_CORE
    # Fail-open: a null id and an unlabeled actor yield None (never raise),
    # so the render omits the field rather than breaking.
    assert actor_render_label(conn, None) is None
    assert actor_render_label(conn, seed_human_actor(conn)) is None
    assert actor_render_label(conn, 999999) is None  # nonexistent actor


def test_set_and_resolve_actor_label(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    assert resolve_actor_by_label(conn, "ben") == aid
    assert resolve_actor_by_label(conn, "missing") is None


def test_set_actor_label_is_idempotent_for_same_pair(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    set_actor_label(conn, aid, "ben")
    rows = conn.execute(
        "SELECT COUNT(*) FROM actor_labels WHERE actor_id = %s",
        (aid,),
    ).fetchone()
    assert rows[0] == 1


def test_set_actor_label_rejects_relabel(conn):
    """A different label for an existing (actor, surface) is no-op'd by
    the ON CONFLICT clause; the prior label remains. The caller must
    delete the prior row to relabel deliberately."""
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    set_actor_label(conn, aid, "ben-alt")
    rows = conn.execute(
        "SELECT label FROM actor_labels WHERE actor_id = %s",
        (aid,),
    ).fetchall()
    assert [r[0] for r in rows] == ["ben"]


def test_actor_label_renders_system_component_for_github_surface(conn):
    aid = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    assert actor_label(conn, aid) == SYSTEM_COMPONENT_YOKE_CORE


def test_actor_label_renders_human_via_actor_labels(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    assert actor_label(conn, aid) == "ben"


def test_actor_label_fails_closed_when_label_missing(conn):
    aid = seed_human_actor(conn)
    with pytest.raises(ActorLabelMissing):
        actor_label(conn, aid)


def test_actor_label_raises_for_unknown_actor(conn):
    with pytest.raises(ActorNotFound):
        actor_label(conn, 999999)


def test_actor_label_never_returns_raw_numeric_id(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    rendered = actor_label(conn, aid)
    assert rendered != str(aid)
    assert not rendered.isdigit()


def test_actor_display_name_prefers_display_surface(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    set_actor_label(conn, aid, "Ben B.", surface=DISPLAY_LABEL_SURFACE)

    assert actor_display_name(conn, aid) == "Ben B."
    assert actor_label(conn, aid) == "ben"


def test_actor_display_name_falls_back_to_github_label(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")

    assert actor_display_name(conn, aid) == "ben"


def test_actor_display_name_falls_back_to_system_component(conn):
    aid = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)

    assert actor_display_name(conn, aid) == SYSTEM_COMPONENT_YOKE_CORE


def test_actor_render_label_sanitizes_display_surface(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "Ben B.", surface=DISPLAY_LABEL_SURFACE)

    assert actor_render_label(conn, aid) == "Ben-B."


def test_actor_label_ambiguous_when_uniqueness_relaxed():
    """Defense-in-depth: if a future schema migration weakens the
    UNIQUE(actor_id, surface) index, the central helper must still
    refuse to pick a label rather than silently emit one of two
    possibilities. We rebuild a fresh DB without the constraint and
    insert two rows directly to provoke the condition."""
    from datetime import datetime, timezone

    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        c.execute(
            "CREATE TABLE actors ("
            "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
            "kind TEXT NOT NULL, "
            "system_component TEXT, "
            "created_at TEXT NOT NULL)"
        )
        c.execute(
            "CREATE TABLE actor_labels ("
            "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
            "actor_id INTEGER NOT NULL, "
            "surface TEXT NOT NULL, "
            "label TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        now = datetime.now(timezone.utc).isoformat()
        aid = c.execute(
            "INSERT INTO actors (kind, system_component, created_at) "
            "VALUES ('human', NULL, %s) RETURNING id",
            (now,),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO actor_labels (actor_id, surface, label, created_at) "
            "VALUES (%s, %s, 'ben', %s), (%s, %s, 'ben-alt', %s)",
            (aid, GITHUB_LABEL_SURFACE, now, aid, GITHUB_LABEL_SURFACE, now),
        )
        with pytest.raises(ActorLabelAmbiguous):
            actor_label(c, aid)
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_labels_for_surface_returns_pairs(conn):
    a = seed_human_actor(conn)
    b = seed_human_actor(conn)
    set_actor_label(conn, a, "alpha")
    set_actor_label(conn, b, "beta")
    pairs = sorted(labels_for_surface(conn))
    assert pairs == [(a, "alpha"), (b, "beta")]


def test_validate_actor_id(conn):
    aid = seed_human_actor(conn)
    assert validate_actor_id(conn, aid) is True
    assert validate_actor_id(conn, 999999) is False


# ---------------------------------------------------------------------------
# actor_label_or_passthrough — the cutover-window reader adapter
# ---------------------------------------------------------------------------


def test_passthrough_resolves_numeric_actor_id(conn):
    aid = seed_human_actor(conn)
    set_actor_label(conn, aid, "ben")
    assert actor_label_or_passthrough(conn, str(aid)) == "ben"


def test_passthrough_returns_text_label_unchanged(conn):
    # Pre-migration shape: column holds a legacy text label, not an
    # actor id. The reader must not try to coerce or validate; the
    # value flows through unchanged so the GitHub render keeps working.
    assert actor_label_or_passthrough(conn, "ben") == "ben"
    assert actor_label_or_passthrough(conn, "skill-simulate") == "skill-simulate"


def test_passthrough_collapses_empty_sentinels(conn):
    assert actor_label_or_passthrough(conn, "") == ""
    assert actor_label_or_passthrough(conn, "null") == ""
    assert actor_label_or_passthrough(conn, "None") == ""


def test_passthrough_failclosed_on_orphan_numeric_id(conn):
    # Numeric values must not bypass the central helper's fail-closed
    # contract; an orphan id with no actor row raises rather than
    # leaking the raw integer as a label.
    with pytest.raises(ActorNotFound):
        actor_label_or_passthrough(conn, "424242")


def test_passthrough_failclosed_when_label_missing(conn):
    aid = seed_human_actor(conn)
    with pytest.raises(ActorLabelMissing):
        actor_label_or_passthrough(conn, str(aid))
