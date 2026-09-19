"""Which roster rows the overview projection computes delivery counts for.

The counts behind a card's merges line cost one ancestry read per item, so
the projection pays for them only where a card will draw a delivery box.
Release and the last day of finished work are those two bands, and they
share one rendering — so the selection has to admit both while staying as
bounded as it was when only Release asked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.item_overview_read import (
    OVERVIEW_DONE_WINDOW,
    _delivery_drawn,
)


def _stamp(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(status: str, **facts: str) -> dict[str, str]:
    return {"status": status, **facts}


def test_a_releasing_item_draws_a_box_whatever_its_timestamps_say() -> None:
    assert _delivery_drawn(_row("release", updated_at=_stamp(timedelta(days=90))))


def test_work_finished_inside_the_window_draws_a_box() -> None:
    recent = _stamp(OVERVIEW_DONE_WINDOW - timedelta(hours=1))
    for status in ("done", "cancelled", "stopped"):
        assert _delivery_drawn(_row(status, merged_at=recent)), status


def test_work_finished_before_the_window_draws_nothing() -> None:
    # The Done band never shows it, so the ancestry read behind its counts
    # would be spent on a card that is not on the page. This is the bound
    # that keeps a caller which skipped the roster window from turning the
    # projection into a scan of every terminal item ever filed.
    stale = _stamp(OVERVIEW_DONE_WINDOW + timedelta(hours=1))
    assert not _delivery_drawn(_row("done", merged_at=stale))


def test_a_terminal_row_with_no_usable_timestamp_draws_nothing() -> None:
    assert not _delivery_drawn(_row("done"))
    assert not _delivery_drawn(_row("done", merged_at="not a timestamp"))


def test_the_live_bands_ask_nothing_of_delivery() -> None:
    # Waiting, Ready and Active draw no delivery box, so their rows must not
    # pay for counts nothing will read.
    for status in ("idea", "planned", "implementing", "reviewing-implementation"):
        assert not _delivery_drawn(_row(status, updated_at=_stamp(timedelta()))), status


def test_the_finished_stamp_falls_back_the_way_the_band_sorts_it() -> None:
    # The card orders Done by merged_at, then updated_at, then created_at;
    # the selection reads the same three in the same order, so a row the
    # band draws is never one the projection skipped.
    recent = _stamp(timedelta(hours=1))
    stale = _stamp(OVERVIEW_DONE_WINDOW + timedelta(hours=1))
    assert _delivery_drawn(_row("done", updated_at=recent, created_at=stale))
    assert _delivery_drawn(_row("done", created_at=recent))
    assert not _delivery_drawn(_row("done", merged_at=stale, updated_at=recent))
