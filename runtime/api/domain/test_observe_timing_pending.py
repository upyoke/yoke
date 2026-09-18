"""Pending delivery is distinct from a permanently absent start."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.observe_timing import (
    PENDING_DELIVERY_WINDOW,
    TIMING_MEASURED,
    TIMING_PENDING_START_DELIVERY,
    TIMING_UNKNOWN_NO_RECORDED_START,
    delivery_is_pending,
    report_owner_elapsed,
)


def test_placeholder_start_inside_window_is_pending() -> None:
    completed = datetime.now(timezone.utc)
    measurement = report_owner_elapsed(
        completed, completed, observed_at=completed, now=completed
    )
    assert measurement.milliseconds is None
    assert measurement.status == TIMING_PENDING_START_DELIVERY
    assert delivery_is_pending(completed, now=completed) is True


def test_placeholder_start_outside_window_is_absent() -> None:
    now = datetime.now(timezone.utc)
    observed = now - PENDING_DELIVERY_WINDOW - timedelta(seconds=1)
    measurement = report_owner_elapsed(
        observed, observed, observed_at=observed, now=now
    )
    assert measurement.status == TIMING_UNKNOWN_NO_RECORDED_START
    assert delivery_is_pending(observed, now=now) is False


def test_repaired_owner_pair_is_measured_after_delay() -> None:
    now = datetime.now(timezone.utc)
    completed = now - timedelta(minutes=20)
    started = completed - timedelta(milliseconds=1649)
    measurement = report_owner_elapsed(
        started, completed, observed_at=completed, now=now
    )
    assert measurement.milliseconds == 1649
    assert measurement.status == TIMING_MEASURED


def test_missing_row_inside_window_is_pending_not_fabricated() -> None:
    now = datetime.now(timezone.utc)
    measurement = report_owner_elapsed(None, None, observed_at=now, now=now)
    assert measurement.milliseconds is None
    assert measurement.status == TIMING_PENDING_START_DELIVERY
