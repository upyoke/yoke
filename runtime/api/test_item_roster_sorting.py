"""Column sorting applies before pagination and keeps a total ordering."""

import pytest

from runtime.api.conftest import insert_item
from runtime.api.item_roster_test_support import read_roster
from yoke_core.domain.item_roster_order import SORT_COLUMNS


@pytest.mark.parametrize("column", SORT_COLUMNS)
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_every_column_pages_all_matches_once(test_db, column, direction):
    for index, title in enumerate(["Zebra", "apple", "apple"]):
        insert_item(
            test_db,
            id=8500 + index,
            title=f"sort-row {title}",
            status="implementing",
            updated_at=f"2026-09-{10 + index:02d}T12:00:00Z",
        )
    test_db.commit()
    rows, cursor = [], None
    while True:
        outcome = read_roster(
            page_size=1,
            search="sort-row",
            sort_column=column,
            sort_direction=direction,
            **({"cursor": cursor} if cursor else {}),
        )
        assert outcome.primary_success, outcome.error
        rows.extend(outcome.result_payload["rows"])
        cursor = outcome.result_payload["next_cursor"]
        if cursor is None:
            break
    assert len(rows) == 3
    assert len({row["public_ref"] for row in rows}) == 3
    if column == "title":
        titles = [row["title"].lower() for row in rows]
        assert titles == sorted(titles, reverse=direction == "desc")
    if column == "updated_at":
        times = [row["updated_at"] for row in rows]
        assert times == sorted(times, reverse=direction == "desc")


def test_cursor_cannot_continue_under_another_sort(test_db):
    for index in range(2):
        insert_item(
            test_db, id=8600 + index, title="cursor-sort-row", status="implementing"
        )
    test_db.commit()
    first = read_roster(
        page_size=1, search="cursor-sort-row", sort_column="title", sort_direction="asc"
    )
    second = read_roster(
        page_size=1,
        search="cursor-sort-row",
        cursor=first.result_payload["next_cursor"],
    )
    assert not second.primary_success
    assert "Reload the Items page" in second.error.message


@pytest.mark.parametrize(
    "payload",
    [{"sort_column": "i.title; DROP TABLE items"}, {"sort_direction": "sideways"}],
)
def test_sort_input_is_allowlisted(test_db, payload):
    outcome = read_roster(page_size=1, **payload)
    assert not outcome.primary_success
    assert "sort" in outcome.error.message


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_timestamp_ties_remain_ordered_across_filtered_pages(test_db, direction):
    for index in range(5):
        insert_item(
            test_db,
            id=8700 + index,
            title="timestamp-tie" if index % 2 == 0 else "excluded-row",
            status="implementing",
            updated_at="2026-09-15T12:00:00Z",
        )
    test_db.commit()
    rows, cursor = [], None
    while True:
        outcome = read_roster(
            page_size=1,
            search="timestamp-tie",
            sort_direction=direction,
            **({"cursor": cursor} if cursor else {}),
        )
        assert outcome.primary_success, outcome.error
        rows.extend(outcome.result_payload["rows"])
        cursor = outcome.result_payload["next_cursor"]
        if cursor is None:
            break
    expected = test_db.execute(
        "SELECT r.public_ref "
        "FROM items i JOIN item_refs r ON r.item_id = i.id "
        "WHERE i.title = %s ORDER BY i.id " + direction.upper(),
        ("timestamp-tie",),
    ).fetchall()
    assert [row["public_ref"] for row in rows] == [row[0] for row in expected]
