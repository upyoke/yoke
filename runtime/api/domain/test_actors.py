"""Tests for actor seeding, naming, and name search.

The theme running through these: a name is what an actor is called, and
never how one is found. Every test that touches renaming or duplicate
names asserts that the ids stay where they were.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actors import (
    ActorNotFound,
    SYSTEM_COMPONENT_YOKE_CORE,
    actor_name,
    actor_name_or_passthrough,
    resolve_actors_by_name,
    seed_human_actor,
    seed_system_actor,
    set_actor_name,
    sole_human_actor_id,
    validate_actor_id,
)
from yoke_core.domain.actor_render import render_actor_name
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
    first = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    assert seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE) == first
    assert actor_name(conn, first) == SYSTEM_COMPONENT_YOKE_CORE


def test_seed_human_actor_creates_distinct_rows(conn):
    a = seed_human_actor(conn)
    b = seed_human_actor(conn)
    assert a != b
    assert validate_actor_id(conn, a) and validate_actor_id(conn, b)


def test_two_humans_may_share_one_name(conn):
    """The constraint that once refused a second Ada Lovelace is gone."""
    first = seed_human_actor(conn, "Ada Lovelace")
    second = seed_human_actor(conn, "Ada Lovelace")

    assert first != second
    assert actor_name(conn, first) == actor_name(conn, second) == "Ada Lovelace"
    assert resolve_actors_by_name(conn, "Ada Lovelace") == sorted([first, second])


def test_set_actor_name_reports_only_real_changes(conn):
    aid = seed_human_actor(conn, "Ada")

    assert set_actor_name(conn, aid, "Ada Lovelace") is True
    assert set_actor_name(conn, aid, "Ada Lovelace") is False
    assert actor_name(conn, aid) == "Ada Lovelace"


def test_set_actor_name_ignores_a_blank_name(conn):
    """An account with no name of its own leaves the actor's name alone."""
    aid = seed_human_actor(conn, "Ada Lovelace")

    assert set_actor_name(conn, aid, "") is False
    assert set_actor_name(conn, aid, None) is False
    assert set_actor_name(conn, aid, "   ") is False
    assert actor_name(conn, aid) == "Ada Lovelace"


def test_renaming_an_actor_moves_no_identity(conn):
    """The id is the identity; a rename changes what people read."""
    aid = seed_human_actor(conn, "Ada Lovelace")
    set_actor_name(conn, aid, "Ada King")

    assert sole_human_actor_id(conn) == aid
    assert resolve_actors_by_name(conn, "Ada Lovelace") == []
    assert resolve_actors_by_name(conn, "Ada King") == [aid]


def test_resolve_actors_by_name_returns_every_match(conn):
    """A list, not an id: the shape refuses to let a caller guess."""
    seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    one = seed_human_actor(conn, "Chris")
    two = seed_human_actor(conn, "Chris")

    assert resolve_actors_by_name(conn, "Chris") == sorted([one, two])
    assert resolve_actors_by_name(conn, "chris") == []  # exact match only
    assert resolve_actors_by_name(conn, "") == []
    assert resolve_actors_by_name(conn, "nobody") == []


def test_resolve_actors_by_name_can_narrow_to_humans(conn):
    system = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)

    assert resolve_actors_by_name(conn, SYSTEM_COMPONENT_YOKE_CORE) == [system]
    assert (
        resolve_actors_by_name(conn, SYSTEM_COMPONENT_YOKE_CORE, kind="human") == []
    )


def test_actor_name_fails_closed_on_an_unknown_actor(conn):
    with pytest.raises(ActorNotFound):
        actor_name(conn, 999999)
    with pytest.raises(ActorNotFound):
        set_actor_name(conn, 999999, "Ada")


def test_actor_name_of_an_unnamed_actor_is_empty_not_an_id(conn):
    aid = seed_human_actor(conn)

    assert actor_name(conn, aid) == ""


def test_sole_human_actor_id_answers_only_for_one_human(conn):
    assert sole_human_actor_id(conn) is None

    first = seed_human_actor(conn, "Ada")
    assert sole_human_actor_id(conn) == first

    seed_human_actor(conn, "Grace")
    assert sole_human_actor_id(conn) is None
    assert sole_human_actor_id(conn, oldest=True) == first


def test_seed_canonical_actors_keeps_the_human_a_universe_already_has(conn):
    """Re-seeding never forks an existing owner into a second actor."""
    from yoke_core.domain.actors import (
        DEFAULT_LOCAL_HUMAN_NAME,
        LOCAL_HUMAN_NAME_ENV,
        seed_canonical_actors,
    )

    system, human = seed_canonical_actors(conn, local_human_name="Ada Lovelace")
    assert actor_name(conn, human) == "Ada Lovelace"
    assert actor_name(conn, system) == SYSTEM_COMPONENT_YOKE_CORE

    # A rename must not make the next seed create a second human.
    set_actor_name(conn, human, "Ada King")
    assert seed_canonical_actors(conn, local_human_name="Ada Lovelace") == (
        system,
        human,
    )
    assert actor_name(conn, human) == "Ada King"
    assert DEFAULT_LOCAL_HUMAN_NAME
    assert LOCAL_HUMAN_NAME_ENV


def test_seed_canonical_actors_name_precedence_for_a_new_universe(
    conn, monkeypatch
):
    from yoke_core.domain.actors import (
        DEFAULT_LOCAL_HUMAN_NAME,
        LOCAL_HUMAN_NAME_ENV,
        seed_canonical_actors,
    )

    monkeypatch.delenv(LOCAL_HUMAN_NAME_ENV, raising=False)
    _, default_human = seed_canonical_actors(conn)
    assert actor_name(conn, default_human) == DEFAULT_LOCAL_HUMAN_NAME


def test_seed_canonical_actors_takes_the_env_injected_name(conn, monkeypatch):
    from yoke_core.domain.actors import LOCAL_HUMAN_NAME_ENV, seed_canonical_actors

    monkeypatch.setenv(LOCAL_HUMAN_NAME_ENV, "env-owner")
    _, human = seed_canonical_actors(conn)
    assert actor_name(conn, human) == "env-owner"


def test_render_actor_name_is_fail_open(conn):
    human = seed_human_actor(conn, "Ada Lovelace")
    assert render_actor_name(conn, human) == "Ada Lovelace"

    system = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
    assert render_actor_name(conn, system) == SYSTEM_COMPONENT_YOKE_CORE

    # Fail-open: a null id, an unnamed actor, and a nonexistent actor all
    # yield None so the view omits the field rather than breaking.
    assert render_actor_name(conn, None) is None
    assert render_actor_name(conn, seed_human_actor(conn)) is None
    assert render_actor_name(conn, 999999) is None


def test_render_actor_name_preserves_spaces_and_collapses_line_breaks(conn):
    """A person is "Ada Lovelace"; only what would split a line is removed."""
    aid = seed_human_actor(conn, "Ada Lovelace")
    assert render_actor_name(conn, aid) == "Ada Lovelace"

    set_actor_name(conn, aid, "Ada\nLovelace")
    assert render_actor_name(conn, aid) == "Ada Lovelace"

    # A control character, a double space, and a zero-width space
    # each collapse away; the interior single space does not.
    set_actor_name(conn, aid, "Ada\a  \u200bKing")
    assert render_actor_name(conn, aid) == "Ada King"


def test_actor_name_or_passthrough_handles_ids_text_and_sentinels(conn):
    aid = seed_human_actor(conn, "Ada Lovelace")

    assert actor_name_or_passthrough(conn, str(aid)) == "Ada Lovelace"
    # A legacy free-text owner token from before actors existed.
    assert actor_name_or_passthrough(conn, "skill-simulate") == "skill-simulate"
    for sentinel in ("", "null", "None"):
        assert actor_name_or_passthrough(conn, sentinel) == ""


def test_actor_name_or_passthrough_fails_closed_on_an_orphan_id(conn):
    with pytest.raises(ActorNotFound):
        actor_name_or_passthrough(conn, "999999")
