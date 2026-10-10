"""Which recipients the idle-timeout wake sweep may route natively."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

import pytest

from yoke_core.hooks import session_message_delivery as delivery


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("state", ["acknowledged", "expired", "cancelled"])
def test_terminal_recipient_is_never_wake_eligible(state: str) -> None:
    assert not delivery.wake_eligible(
        recipient_state=state,
        last_activity_at=None,
        now=NOW + timedelta(hours=1),
        idle_threshold=timedelta(seconds=60),
    )


def test_pending_without_post_message_hook_becomes_wake_eligible() -> None:
    assert delivery.wake_eligible(
        recipient_state="pending",
        last_activity_at=NOW - timedelta(seconds=60),
        now=NOW,
        idle_threshold=timedelta(seconds=60),
    )


def test_live_injected_unacknowledged_recipient_is_never_woken() -> None:
    assert not delivery.wake_eligible(
        recipient_state="injected",
        last_activity_at=NOW - timedelta(seconds=10),
        now=NOW,
        idle_threshold=timedelta(seconds=60),
    )


def test_recent_heartbeat_skips_native_wake() -> None:
    assert not delivery.wake_eligible(
        recipient_state="pending",
        last_activity_at=NOW - timedelta(seconds=10),
        now=NOW,
        idle_threshold=timedelta(seconds=60),
    )


class _UnknownOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize(
    "offset", [timedelta(0), timedelta(hours=5, minutes=30), timedelta(hours=-4)]
)
@pytest.mark.parametrize("microseconds,eligible", [(-1, True), (0, True), (1, False)])
def test_idle_cutoff_preserves_microseconds_across_qualified_offsets(
    offset, microseconds, eligible
):
    now = datetime(1970, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)
    activity = (
        now - timedelta(seconds=60) + timedelta(microseconds=microseconds)
    ).astimezone(timezone(offset))
    assert (
        delivery.wake_eligible(
            recipient_state="pending",
            last_activity_at=activity,
            now=now,
            idle_threshold=timedelta(seconds=60),
        )
        is eligible
    )


@pytest.mark.parametrize("field", ["now", "last_activity_at"])
@pytest.mark.parametrize(
    "bad",
    [
        datetime(2026, 8, 22, 20),
        "2026-08-22T20:00:00Z",
        datetime(2026, 8, 22, 20, tzinfo=_UnknownOffset()),
    ],
)
def test_wake_eligibility_refuses_non_native_or_unknown_offset_clocks(field, bad):
    from yoke_contracts.timestamps import InvalidInstant

    values = {"now": NOW, "last_activity_at": NOW - timedelta(seconds=60)}
    values[field] = bad
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        delivery.wake_eligible(
            recipient_state="pending",
            idle_threshold=timedelta(seconds=60),
            **values,
        )


@pytest.mark.parametrize("bad", [None, datetime(2026, 8, 22, 20)])
def test_missing_activity_does_not_bypass_reference_clock_validation(bad):
    from yoke_contracts.timestamps import InvalidInstant

    with pytest.raises(InvalidInstant, match="invalid_instant"):
        delivery.wake_eligible(
            recipient_state="pending",
            last_activity_at=None,
            now=bad,
            idle_threshold=timedelta(seconds=60),
        )
