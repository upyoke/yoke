"""SQL adapters retain exact instants and reject unparsed inputs before SQL."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant
from yoke_core.domain.db_helpers import instant_parameter


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_postgres_parameter_is_native_and_microseconds_survive(test_db, zone):
    value = datetime(
        1969,
        12,
        31,
        18,
        29,
        59,
        123456,
        tzinfo=timezone(timedelta(hours=-5, minutes=-30)),
    )
    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    parameter = instant_parameter(test_db, value)
    actual, kind = test_db.execute(
        "SELECT %s,pg_typeof(%s)::text", (parameter, parameter)
    ).fetchone()
    assert kind == "timestamp with time zone"
    assert actual == datetime(1969, 12, 31, 23, 59, 59, 123456, timezone.utc)
    assert parameter.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "value", [0, "2026-10-08T00:00:00Z", "", datetime(2026, 10, 8)]
)
def test_unparsed_parameter_refuses_before_connection_discovery(value):
    class UnusedConnection:
        def __getattribute__(self, name):
            raise AssertionError("invalid instant inspected connection")

    with pytest.raises(InvalidInstant, match="invalid_instant"):
        instant_parameter(UnusedConnection(), value)


def test_optional_native_parameter_stays_null():
    assert instant_parameter(object(), None) is None
