"""Which recipients the idle-timeout wake sweep may route natively."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
