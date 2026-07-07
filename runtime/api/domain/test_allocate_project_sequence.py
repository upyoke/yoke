"""Per-project sequence allocation, on real Postgres.

Sequence allocation is control-plane authority behavior (it decides the next
public reference number for a project), so it is proven against a disposable
real-Postgres database. The cloud-runtime cutover backfilled ``project_sequence =
items.id``; the allocator must continue from ``MAX + 1`` per project rather than
refilling low gaps, so buzz (whose backfilled band starts at 662) never hands a
new item a number that collides backward into already-issued references.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.project_identity import allocate_project_sequence
from yoke_core.domain.project_seed_test_helpers import seed_project_identities

YOKE_PROJECT_ID = 1
BUZZ_PROJECT_ID = 2


@pytest.fixture()
def seeded(test_db):
    conn = test_db
    seed_project_identities(conn)
    conn.commit()
    return conn


def _insert_item(conn, item_id: int, project_id: int, seq: int) -> None:
    conn.execute(
        "INSERT INTO items (id, title, created_at, updated_at, project_id, "
        "project_sequence) VALUES (%s, 't', '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z', %s, %s)",
        (item_id, project_id, seq),
    )


def test_empty_project_allocates_one(seeded):
    assert allocate_project_sequence(seeded, BUZZ_PROJECT_ID) == 1


def test_continues_from_max_not_smallest_gap(seeded):
    # Mirror the backfilled buzz band: high, gap-pocked (no 1..661).
    _insert_item(seeded, 662, BUZZ_PROJECT_ID, 662)
    _insert_item(seeded, 1882, BUZZ_PROJECT_ID, 1882)
    seeded.commit()
    # MAX+1, not the smallest-unused 1.
    assert allocate_project_sequence(seeded, BUZZ_PROJECT_ID) == 1883


def test_gap_below_max_is_not_refilled(seeded):
    _insert_item(seeded, 10, YOKE_PROJECT_ID, 1)
    _insert_item(seeded, 11, YOKE_PROJECT_ID, 2)
    _insert_item(seeded, 14, YOKE_PROJECT_ID, 5)  # gap at 3,4
    seeded.commit()
    # Monotonic handle: the 3/4 gap is never reused.
    assert allocate_project_sequence(seeded, YOKE_PROJECT_ID) == 6


def test_allocation_is_per_project(seeded):
    _insert_item(seeded, 662, BUZZ_PROJECT_ID, 662)
    _insert_item(seeded, 5, YOKE_PROJECT_ID, 5)
    seeded.commit()
    assert allocate_project_sequence(seeded, BUZZ_PROJECT_ID) == 663
    assert allocate_project_sequence(seeded, YOKE_PROJECT_ID) == 6
