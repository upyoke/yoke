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


@pytest.mark.parametrize("offset", [0, -240, 345])
def test_usage_prices_at_native_offered_instant(offset):
    from yoke_contracts.board.sections_sessions_cells import _display_usage

    offered = parse_instant("2026-04-12T10:31:00.000001Z").astimezone(
        timezone(timedelta(minutes=offset))
    )

    class DB:
        def query(self, sql, params):
            assert "effective_at <= %s" in sql
            assert params == (parse_instant("2026-04-12T10:31:00.000001Z"),)
            assert isinstance(params[0], datetime)
            return [("revision", offered)]

    db = DB()
    db._board_model_catalogs = {"revision": []}
    assert isinstance(_display_usage(db, None, offered), str)
    assert isinstance(_display_usage(db, None, None), str)


def test_board_wire_codec_preserves_native_values_without_mutation():
    import json
    from datetime import date
    from decimal import Decimal
    from yoke_contracts.board.data import _encode_value, _decode_value

    stamp = parse_instant("2026-04-12T10:31:00.000001Z")
    values = {"clock": stamp, "cost": Decimal("0.0000123"), "day": date(2026, 4, 12)}
    payload = _encode_value(values)
    before = json.dumps(payload, sort_keys=True)
    assert _decode_value(json.loads(before)) == values
    assert json.dumps(payload, sort_keys=True) == before
