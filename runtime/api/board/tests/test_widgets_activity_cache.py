"""Cross-process board activity cache tests (item_activity_days sourcing)."""

from __future__ import annotations

from datetime import date, timedelta

from yoke_contracts.board import activity_cache as activity_cache_mod
from yoke_core.board.db import BoardDB
from runtime.api.board.tests.conftest import insert_activity_day, insert_item_raw
from yoke_contracts.board.widgets import _compute_lifetime_activity


def _item_created_day(test_db_path: str, item_id: int, day: str) -> None:
    insert_item_raw(test_db_path, [
        (item_id, f"item-{item_id}", "idea", "issue", "yoke", 0,
         f"{day}T12:00:00Z", f"{day}T12:00:00Z"),
    ])


def _activity_day(test_db_path: str, item_id: int, day: str) -> None:
    insert_activity_day(test_db_path, "yoke", item_id, day)


def test_activity_counts_reuse_cross_process_cache(test_db_path, monkeypatch):
    today = date.today().isoformat()
    _item_created_day(test_db_path, 1, today)
    _activity_day(test_db_path, 1, today)

    with BoardDB(test_db_path) as db:
        active, _ = _compute_lifetime_activity(db, "yoke")
    assert active == 1

    def boom(*_args, **_kwargs):  # pragma: no cover - asserted not to run
        raise AssertionError("activity cache missed unexpectedly")

    monkeypatch.setattr(activity_cache_mod, "_query_activity_day_counts", boom)
    with BoardDB(test_db_path) as db:
        active, _ = _compute_lifetime_activity(db, "yoke")
    assert active == 1


def test_activity_counts_invalidate_on_new_activity_row(test_db_path):
    today = date.today()
    day_a = (today - timedelta(days=1)).isoformat()
    day_b = today.isoformat()
    _item_created_day(test_db_path, 1, day_a)
    _item_created_day(test_db_path, 2, day_b)
    _activity_day(test_db_path, 1, day_a)

    with BoardDB(test_db_path) as db:
        active, _ = _compute_lifetime_activity(db, "yoke")
    assert active == 1

    # A new (project, item, day) tuple advances MAX(id) — the cache must
    # invalidate and pick up the second day.
    _activity_day(test_db_path, 2, day_b)
    with BoardDB(test_db_path) as db:
        active, _ = _compute_lifetime_activity(db, "yoke")
    assert active == 2
