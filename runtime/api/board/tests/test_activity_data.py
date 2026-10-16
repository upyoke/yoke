"""Board activity snapshots read current item activity days."""

from __future__ import annotations

from datetime import date, timedelta

from yoke_core.board.db import BoardDB
from runtime.api.board.tests.conftest import insert_activity_day, insert_item_raw
from yoke_contracts.board.widgets import _compute_lifetime_activity


def _item_created_day(test_db_path: str, item_id: int, day: str) -> None:
    insert_item_raw(
        test_db_path,
        [
            (
                item_id,
                f"item-{item_id}",
                "idea",
                "issue",
                "yoke",
                0,
                f"{day}T12:00:00Z",
                f"{day}T12:00:00Z",
            ),
        ],
    )


def _activity_day(test_db_path: str, item_id: int, day: str) -> None:
    insert_activity_day(test_db_path, "yoke", item_id, day)


def test_activity_counts_refresh_for_each_snapshot(test_db_path):
    today = date.today()
    day_a = (today - timedelta(days=1)).isoformat()
    day_b = today.isoformat()
    _item_created_day(test_db_path, 1, day_a)
    _item_created_day(test_db_path, 2, day_b)
    _activity_day(test_db_path, 1, day_a)

    with BoardDB(test_db_path) as db:
        active, _ = _compute_lifetime_activity(db, "yoke")
    assert active == 1

    # A fresh snapshot must see the second activity day.
    _activity_day(test_db_path, 2, day_b)
    with BoardDB(test_db_path) as db:
        active, _ = _compute_lifetime_activity(db, "yoke")
    assert active == 2
