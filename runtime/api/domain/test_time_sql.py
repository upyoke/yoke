"""Native SQL clock windows preserve instants across database session zones."""

from datetime import timedelta

import pytest

from yoke_contracts.time_sql import now_sql


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"offset_days": -30, "offset_hours": -1}, "at most one of"),
        ({"offset_days": -30, "offset_modifier": "%s"}, "mutually exclusive"),
    ],
)
def test_ambiguous_clock_modifiers_refuse(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        now_sql(**kwargs)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
@pytest.mark.parametrize(
    "kwargs,seconds",
    [
        ({}, 0),
        ({"offset_days": -30}, -30 * 86400),
        ({"offset_hours": 7}, 7 * 3600),
        ({"offset_minutes": -15}, -15 * 60),
        ({"offset_modifier": "%s"}, -45),
    ],
)
def test_native_clock_offsets_preserve_elapsed_seconds(test_db, zone, kwargs, seconds):
    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    fragment = now_sql(**kwargs)
    params = ("-45 seconds",) if "offset_modifier" in kwargs else ()
    row = test_db.execute(
        f"SELECT now(), {fragment}, pg_typeof({fragment})::text", params * 2
    ).fetchone()
    assert row[2] == "timestamp with time zone"
    assert row[1] - row[0] == timedelta(seconds=seconds)
