"""Session age uses native instants and explicit absence."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.board import sections_sessions_rendering as rendering
from yoke_contracts.timestamps import InvalidInstant, parse_instant


@pytest.mark.parametrize("offset", [0, -240, 345])
def test_session_age_preserves_microsecond_thresholds(monkeypatch, offset):
    now = parse_instant("2026-04-12T10:31:00.000001Z")
    monkeypatch.setattr(rendering, "utc_now", lambda: now)
    zone = timezone(timedelta(minutes=offset))
    assert (
        rendering._format_session_age(
            (now - timedelta(seconds=60, microseconds=-1)).astimezone(zone)
        )
        == "59s"
    )
    assert (
        rendering._format_session_age((now - timedelta(seconds=60)).astimezone(zone))
        == "1m"
    )
    assert rendering._format_session_age(None) == "?"


@pytest.mark.parametrize(
    "invalid", ["", "null", "2026-04-12T10:30:00", datetime(2026, 4, 12), 1770000000]
)
def test_session_age_refuses_unknown_clock_guessing(invalid):
    with pytest.raises(InvalidInstant):
        rendering._format_session_age(invalid)
