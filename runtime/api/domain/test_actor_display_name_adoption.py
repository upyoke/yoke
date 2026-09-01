"""Adopting an account-owned display name onto an actor's display surface."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.actor_labels import (
    DISPLAY_LABEL_SURFACE,
    GITHUB_LABEL_SURFACE,
)
from yoke_core.domain.actor_display import (
    actor_display_name,
    set_actor_display_name,
)
from yoke_core.domain.actors import (
    ActorLabelMissing,
    seed_human_actor,
    seed_system_actor,
    set_actor_label,
)
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


def _display_rows(conn: Any, actor_id: int) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT label FROM actor_labels WHERE actor_id = %s AND surface = %s",
            (actor_id, DISPLAY_LABEL_SURFACE),
        ).fetchall()
    ]


def test_adoption_writes_the_display_row_and_wins_over_the_github_label(conn):
    actor_id = seed_human_actor(conn)
    set_actor_label(conn, actor_id, "bee", surface=GITHUB_LABEL_SURFACE)
    assert actor_display_name(conn, actor_id) == "bee"

    assert set_actor_display_name(conn, actor_id, "Bee Bauman") is True
    assert actor_display_name(conn, actor_id) == "Bee Bauman"
    assert _display_rows(conn, actor_id) == ["Bee Bauman"]


def test_a_renamed_account_updates_the_same_row(conn):
    actor_id = seed_human_actor(conn)
    set_actor_display_name(conn, actor_id, "Alex Kim")

    assert set_actor_display_name(conn, actor_id, "Alex Rivera") is True
    assert _display_rows(conn, actor_id) == ["Alex Rivera"]


def test_an_unchanged_name_reports_no_change(conn):
    actor_id = seed_human_actor(conn)
    assert set_actor_display_name(conn, actor_id, "Alex Kim") is True
    assert set_actor_display_name(conn, actor_id, "Alex Kim") is False
    assert _display_rows(conn, actor_id) == ["Alex Kim"]


@pytest.mark.parametrize("absent", [None, "", "   "])
def test_an_absent_name_leaves_the_fallback_chain_untouched(conn, absent):
    actor_id = seed_human_actor(conn)
    set_actor_label(conn, actor_id, "bee", surface=GITHUB_LABEL_SURFACE)

    assert set_actor_display_name(conn, actor_id, absent) is False
    assert _display_rows(conn, actor_id) == []
    assert actor_display_name(conn, actor_id) == "bee"


def test_an_absent_name_never_clears_a_display_row_an_earlier_sync_wrote(conn):
    actor_id = seed_human_actor(conn)
    set_actor_display_name(conn, actor_id, "Alex Kim")

    assert set_actor_display_name(conn, actor_id, None) is False
    assert _display_rows(conn, actor_id) == ["Alex Kim"]


def test_an_actor_with_no_name_and_no_fallback_still_fails_closed(conn):
    actor_id = seed_human_actor(conn)
    assert set_actor_display_name(conn, actor_id, None) is False
    with pytest.raises(ActorLabelMissing):
        actor_display_name(conn, actor_id)


def test_adoption_touches_only_the_named_actor_in_a_multi_member_org(conn):
    first = seed_human_actor(conn)
    second = seed_human_actor(conn)
    third = seed_system_actor(conn, "yoke-core")
    set_actor_label(conn, second, "second-handle", surface=GITHUB_LABEL_SURFACE)

    set_actor_display_name(conn, first, "Alex Kim")

    assert _display_rows(conn, first) == ["Alex Kim"]
    assert _display_rows(conn, second) == []
    assert _display_rows(conn, third) == []
    assert actor_display_name(conn, second) == "second-handle"
    assert actor_display_name(conn, third) == "yoke-core"


def test_two_members_of_one_org_may_share_a_display_name(conn):
    first = seed_human_actor(conn)
    second = seed_human_actor(conn)

    assert set_actor_display_name(conn, first, "Alex Kim") is True
    assert set_actor_display_name(conn, second, "Alex Kim") is True

    assert actor_display_name(conn, first) == "Alex Kim"
    assert actor_display_name(conn, second) == "Alex Kim"


def test_surrounding_whitespace_is_trimmed_before_storage(conn):
    actor_id = seed_human_actor(conn)
    assert set_actor_display_name(conn, actor_id, "  Alex Kim  ") is True
    assert _display_rows(conn, actor_id) == ["Alex Kim"]
    assert set_actor_display_name(conn, actor_id, "Alex Kim") is False
