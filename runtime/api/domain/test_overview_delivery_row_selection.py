"""Which roster rows the overview projection computes delivery counts for.

The counts behind a card's merges line cost one ancestry read per item, so
the projection pays for them only where a card will draw a delivery box.
Release and the last day of finished work are those two bands, and they
share one rendering — so the selection has to admit both while staying as
bounded as it was when only Release asked.

The selection reads the finished facts the enrichment already resolved onto
the row rather than re-deriving them from timestamps, so a row the band
draws is never one the projection skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.item_overview_read import (
    OVERVIEW_DONE_WINDOW,
    _delivery_drawn,
)


def _stamp(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row(status: str, **facts) -> dict:
    return {"status": status, **facts}


def _finished(status: str, delta: timedelta) -> dict:
    """A row as the enrichment leaves it once the item has finished."""
    return _row(status, finished=True, finished_at=_stamp(delta))


def test_a_releasing_item_draws_a_box_whatever_its_timestamps_say() -> None:
    assert _delivery_drawn(_row("release", updated_at=_stamp(timedelta(days=90))))


def test_work_finished_inside_the_window_draws_a_box() -> None:
    for status in ("done", "cancelled"):
        row = _finished(status, OVERVIEW_DONE_WINDOW - timedelta(hours=1))
        assert _delivery_drawn(row), status


def test_work_finished_before_the_window_draws_nothing() -> None:
    # The Done band never shows it, so the ancestry read behind its counts
    # would be spent on a card that is not on the page. This is the bound
    # that keeps a caller which skipped the roster window from turning the
    # projection into a scan of every terminal item ever filed. The window
    # is applied when the finishing time is resolved, so a row outside it
    # arrives here with no finished stamp at all.
    assert not _delivery_drawn(_row("done", finished=True, finished_at=None))


def test_a_row_the_enrichment_never_resolved_draws_nothing() -> None:
    assert not _delivery_drawn(_row("done"))


def test_a_stopped_item_draws_nothing_however_recently_it_halted() -> None:
    # `stopped` is terminal for resource release but is a pause, not an
    # ending, so it is never finished and never carries a finishing time.
    assert not _delivery_drawn(
        _row("stopped", finished=False, finished_at=None, updated_at=_stamp(timedelta()))
    )


def test_the_live_bands_ask_nothing_of_delivery() -> None:
    # Waiting, Ready and Active draw no delivery box, so their rows must not
    # pay for counts nothing will read.
    for status in ("idea", "planned", "implementing", "reviewing-implementation"):
        row = _row(status, finished=False, finished_at=None, updated_at=_stamp(timedelta()))
        assert not _delivery_drawn(row), status


def test_the_merge_time_no_longer_decides_anything_here() -> None:
    # An item merges when its code lands and finishes when close-out ends,
    # and the gap between them is routinely more than the window. Neither
    # direction may sway the selection now.
    merged_long_ago = _finished("done", timedelta(hours=1))
    merged_long_ago["merged_at"] = _stamp(timedelta(hours=30))
    assert _delivery_drawn(merged_long_ago)

    merged_just_now = _row(
        "done", finished=True, finished_at=None, merged_at=_stamp(timedelta(hours=1)),
    )
    assert not _delivery_drawn(merged_just_now)
