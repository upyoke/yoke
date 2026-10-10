"""Native rehearsal freshness preserves strict instant precision and absence."""

from datetime import datetime, timedelta

import pytest
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.schema_fingerprint import (
    FRESHNESS_WINDOW_MINUTES,
    freshness_expired,
)


class TestFreshnessWindow:
    def test_just_rehearsed_not_expired(self) -> None:
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:05:00Z",
        )

    def test_within_window_not_expired(self) -> None:
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:29:00Z",
        )

    def test_at_window_boundary_not_expired(self) -> None:
        # Boundary: exactly 30 minutes = not expired (strict '>').
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:30:00Z",
        )

    def test_past_window_expired(self) -> None:
        assert freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:31:00Z",
        )

    def test_missing_rehearsed_at_expired(self) -> None:
        assert freshness_expired(None)
        assert freshness_expired("")

    def test_malformed_rehearsed_at_expired(self) -> None:
        assert freshness_expired("not-a-timestamp")
        assert freshness_expired("2026-99-99T99:99:99Z")

    def test_custom_window(self) -> None:
        # A 5-minute window tightens freshness accordingly.
        assert freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:06:00Z",
            window_minutes=5,
        )
        assert not freshness_expired(
            "2026-04-23T12:00:00Z",
            now="2026-04-23T12:04:00Z",
            window_minutes=5,
        )

    def test_plus_00_format_accepted(self) -> None:
        # Qualified offsets denote the same native instant.
        assert not freshness_expired(
            "2026-04-23T12:00:00+00:00",
            now="2026-04-23T12:05:00+00:00",
        )

    def test_default_window_is_thirty_minutes(self) -> None:
        assert FRESHNESS_WINDOW_MINUTES == 30


@pytest.mark.parametrize(
    "offset",
    [
        "1969-12-31T23:59:59.123456Z",
        "1969-12-31T18:59:59.123456-05:00",
        "1970-01-01T05:29:59.123456+05:30",
    ],
)
def test_freshness_preserves_exact_microsecond_boundary(offset):
    stamp = parse_instant(offset)
    boundary = stamp + timedelta(minutes=FRESHNESS_WINDOW_MINUTES)
    assert not freshness_expired(stamp, now=boundary)
    assert not freshness_expired(offset, now=boundary)
    assert freshness_expired(stamp, now=boundary + timedelta(microseconds=1))


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00-00:00",
        0,
        datetime(1970, 1, 1),
    ],
)
def test_invalid_current_clock_refuses_without_defaulting(bad):
    with pytest.raises(InvalidInstant):
        freshness_expired(None, now=bad)
    assert freshness_expired(bad, now=parse_instant("1970-01-01T00:00:00Z"))
