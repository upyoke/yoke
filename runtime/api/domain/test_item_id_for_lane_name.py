"""item_id_for_lane_name: lane names resolve by lane record or public ref.

The number in ``PREFIX-N`` is a project sequence. ``lane_ref_db`` makes that
number also another item's ``items.id``, so a reader that takes it as the
storage key returns the wrong item.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.lane_ref_test_support import lane_ref_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.item_worktree_resolution import item_id_for_lane_name


@pytest.fixture
def conn(tmp_path):
    with lane_ref_db(tmp_path) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("YOK-60", 600),
        ("BUZ-60", 800),
        ("trial/BUZ-60", 800),
        ("/BUZ-60/", 800),
    ],
)
def test_public_ref_resolves_through_its_project(conn, name, expected):
    assert item_id_for_lane_name(conn, name) == expected


@pytest.mark.parametrize("name", ["", "main", "60", "NOPE-60", "YOK-61", "YOK-60-x"])
def test_names_without_an_item_resolve_to_none(conn, name):
    assert item_id_for_lane_name(conn, name) is None


def test_recorded_lane_wins_over_ref_shape(conn):
    now = iso8601_now()
    conn.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, lane_role, state, created_at, updated_at) "
        "VALUES (800, 'YOK-60', 'implementation', 'active', %s, %s)",
        (now, now),
    )
    conn.commit()
    assert item_id_for_lane_name(conn, "YOK-60") == 800


def test_no_connection_resolves_nothing():
    assert item_id_for_lane_name(None, "YOK-60") is None
