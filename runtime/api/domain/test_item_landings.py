"""An item keeps every landing it made, not only its newest.

Before this table an item that landed four times in one day was
indistinguishable from one that landed once: five single-valued columns, each
overwritten by the next landing, and the merge commit stored nowhere. These
tests pin the two halves that fixes — a second landing reads as a second row
rather than as a replacement, and the item's own newest-landing columns keep
meaning exactly what they meant.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.item_landings import (
    ItemLanding,
    append_landing,
    landing_counts,
    landings_for_item,
)
from yoke_core.domain.item_landings_schema import (
    ROUTE_FAST_FORWARD,
    ROUTE_MERGE_QUEUE,
    ROUTE_STANDALONE,
)

FIRST_CANDIDATE = "a" * 40
FIRST_MERGE = "b" * 40
SECOND_CANDIDATE = "c" * 40
SECOND_MERGE = "d" * 40
SAME_INSTANT = "2026-09-19T22:15:00Z"


def _landing(item_id: int, *, merge: str, candidate: str, **overrides) -> ItemLanding:
    fields = {
        "item_id": item_id,
        "merge_sha": merge,
        "candidate_sha": candidate,
        "target_branch": "main",
        "route": ROUTE_STANDALONE,
        "landed_at": SAME_INSTANT,
    }
    fields.update(overrides)
    return ItemLanding(**fields)


def _seed(conn, *, item_id: int, status: str = "release") -> None:
    insert_item(
        conn,
        id=item_id,
        title="Item that lands",
        workflow_id="dash",
        status=status,
    )


def test_two_landings_read_as_two_rows_with_distinct_merges(test_db):
    """The case the table exists for: a re-landing adds, never replaces."""
    _seed(test_db, item_id=9101)
    append_landing(
        test_db,
        _landing(9101, merge=FIRST_MERGE, candidate=FIRST_CANDIDATE),
    )
    append_landing(
        test_db,
        _landing(9101, merge=SECOND_MERGE, candidate=SECOND_CANDIDATE),
    )
    test_db.commit()

    rows = landings_for_item(test_db, 9101)

    assert len(rows) == 2
    assert [row.merge_sha for row in rows] == [FIRST_MERGE, SECOND_MERGE]
    assert [row.candidate_sha for row in rows] == [FIRST_CANDIDATE, SECOND_CANDIDATE]


def test_the_items_newest_landing_columns_still_name_the_second_landing(test_db):
    """The item columns keep meaning "the newest landing", unchanged."""
    _seed(test_db, item_id=9102)
    append_landing(
        test_db,
        _landing(9102, merge=FIRST_MERGE, candidate=FIRST_CANDIDATE),
    )
    test_db.execute(
        "UPDATE items SET merged_at=%s, merge_queue_pr_number=%s WHERE id=%s",
        ("2026-09-19T20:00:00Z", "1201", 9102),
    )
    append_landing(
        test_db,
        _landing(9102, merge=SECOND_MERGE, candidate=SECOND_CANDIDATE),
    )
    test_db.execute(
        "UPDATE items SET merged_at=%s, merge_queue_pr_number=%s WHERE id=%s",
        ("2026-09-19T22:15:00Z", "1202", 9102),
    )
    test_db.commit()

    newest = landings_for_item(test_db, 9102)[-1]
    row = test_db.execute(
        "SELECT merged_at, merge_queue_pr_number FROM items WHERE id=%s", (9102,)
    ).fetchone()

    assert newest.merge_sha == SECOND_MERGE
    assert str(row[0]) == "2026-09-19T22:15:00Z"
    assert str(row[1]) == "1202"


def test_an_item_that_landed_once_has_exactly_one_row(test_db):
    """One landing behaves as it always did: one row, nothing else implied."""
    _seed(test_db, item_id=9103)
    append_landing(
        test_db,
        _landing(9103, merge=FIRST_MERGE, candidate=FIRST_CANDIDATE),
    )
    test_db.commit()

    rows = landings_for_item(test_db, 9103)

    assert len(rows) == 1
    assert rows[0].route == ROUTE_STANDALONE
    assert landing_counts(test_db, [9103]) == {9103: 1}


def test_re_recording_the_same_landing_converges_instead_of_duplicating(test_db):
    """A close-out re-entered after a dead wait must not invent a landing."""
    _seed(test_db, item_id=9104)
    landing = _landing(9104, merge=FIRST_MERGE, candidate=FIRST_CANDIDATE)

    assert append_landing(test_db, landing) is True
    assert append_landing(test_db, landing) is False
    test_db.commit()

    assert len(landings_for_item(test_db, 9104)) == 1


def test_landings_sharing_a_timestamp_still_have_one_newest(test_db):
    """``id`` is the tiebreaker, because two landings can share a clock tick."""
    _seed(test_db, item_id=9105)
    append_landing(
        test_db,
        _landing(
            9105,
            merge=FIRST_MERGE,
            candidate=FIRST_CANDIDATE,
            landed_at=SAME_INSTANT,
        ),
    )
    append_landing(
        test_db,
        _landing(
            9105,
            merge=SECOND_MERGE,
            candidate=SECOND_CANDIDATE,
            landed_at=SAME_INSTANT,
        ),
    )
    test_db.commit()

    rows = landings_for_item(test_db, 9105)

    assert rows[0].id < rows[1].id
    assert rows[-1].merge_sha == SECOND_MERGE


def test_every_route_a_landing_can_take_is_storable(test_db):
    """merge-queue, standalone, and fast-forward are the three answers."""
    _seed(test_db, item_id=9106)
    for index, route in enumerate(
        (ROUTE_MERGE_QUEUE, ROUTE_STANDALONE, ROUTE_FAST_FORWARD)
    ):
        append_landing(
            test_db,
            _landing(
                9106,
                merge=f"{index}" * 40,
                candidate=FIRST_CANDIDATE,
                route=route,
                pr_number="1301" if route == ROUTE_MERGE_QUEUE else "",
            ),
        )
    test_db.commit()

    rows = landings_for_item(test_db, 9106)

    assert [row.route for row in rows] == [
        ROUTE_MERGE_QUEUE,
        ROUTE_STANDALONE,
        ROUTE_FAST_FORWARD,
    ]
    assert rows[0].pr_number == "1301"


def test_an_item_that_never_landed_is_absent_from_the_counts(test_db):
    """Absent, not zero, so "never landed" is distinguishable from "landed"."""
    _seed(test_db, item_id=9107, status="implementing")
    _seed(test_db, item_id=9108)
    append_landing(
        test_db,
        _landing(9108, merge=FIRST_MERGE, candidate=FIRST_CANDIDATE),
    )
    test_db.commit()

    assert landing_counts(test_db, [9107, 9108]) == {9108: 1}
