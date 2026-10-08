"""Native/wire instant equivalence, strict validation and JSON boundaries."""

from datetime import datetime, timedelta, timezone
import json
import random

import pytest

from yoke_contracts.timestamps import (
    InvalidInstant,
    as_utc,
    format_instant,
    iso8601_now,
    parse_instant,
    temporal_wire,
    utc_now,
)


def test_generated_wire_roundtrips_preserve_instants_and_microseconds():
    generator = random.Random(1)
    for _ in range(1000):
        offset = timezone(timedelta(minutes=generator.randrange(-1439, 1440)))
        value = datetime(2, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=generator.randrange(3_000_000),
            seconds=generator.randrange(86400),
            microseconds=generator.randrange(1_000_000),
        )
        value = value.astimezone(offset)
        wire = format_instant(value)
        assert len(wire) == 27
        assert wire.endswith("Z")
        assert parse_instant(wire) == as_utc(value)
        assert parse_instant(wire).microsecond == value.microsecond


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-08T16:30:00.123456Z",
        "2026-10-08T12:30:00.123456-04:00",
        "2026-10-08T22:00:00.123456+05:30",
    ],
)
def test_offset_equivalent_values_have_identical_canonical_bytes(value):
    assert format_instant(value) == "2026-10-08T16:30:00.123456Z"


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        123,
        "2026-10-08",
        "2026-10-08T16:30:00",
        "2026-10-08 16:30:00Z",
        "2026-W41-4T16:30:00Z",
        "2026-02-29T00:00:00Z",
        "2026-10-08T16:30:00+24:00",
        "2026-10-08T16:30:00+00:99",
        "2026-10-08T16:30:00-00:00",
        "2026-10-08T16:30:60Z",
        "2026-10-08T16:30:00.1234567Z",
        datetime(2026, 10, 8),
    ],
)
def test_invalid_or_unknown_inputs_refuse_without_guessing(value):
    with pytest.raises(InvalidInstant, match="invalid_instant.*explicit UTC offset"):
        parse_instant(value)


def test_whole_seconds_are_padded_without_recovering_precision():
    assert format_instant("2026-10-08T16:30:00Z") == "2026-10-08T16:30:00.000000Z"


def test_utc_producers_keep_the_native_and_wire_types_distinct():
    assert utc_now().utcoffset() == timedelta(0)
    assert isinstance(iso8601_now(), str)
    assert parse_instant(iso8601_now()).utcoffset() == timedelta(0)


def test_wire_conversion_preserves_nulls_and_opaque_historical_strings():
    instant = datetime(
        2026, 10, 8, 12, 30, 0, 123456, tzinfo=timezone(timedelta(hours=-4))
    )
    original = {
        "at": instant,
        "nested": (None, {"at": instant}),
        "historical": "2026-10-08 12:30:00",
        "epoch": 123,
    }
    result = temporal_wire(original)
    assert result == {
        "at": "2026-10-08T16:30:00.123456Z",
        "nested": [None, {"at": "2026-10-08T16:30:00.123456Z"}],
        "historical": original["historical"],
        "epoch": 123,
    }
    json.dumps(result)
    assert original["at"] is instant


def test_wire_boundary_refuses_naive_native_results():
    with pytest.raises(InvalidInstant):
        temporal_wire({"at": datetime(2026, 10, 8)})


def test_http_cli_and_replay_ledger_serialize_identical_temporal_results():
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_core.domain.function_call_ledger import serialize_result

    result = {
        "at": datetime(2026, 10, 8, tzinfo=timezone(timedelta(hours=5))),
        "nested": [None, {"at": datetime(2026, 10, 8, tzinfo=timezone.utc)}],
    }
    response = FunctionCallResponse(
        success=True, function="test.read", version="v1", result=result
    )
    wire = response.model_dump()["result"]
    assert wire == response.model_dump(mode="json")["result"]
    assert wire == json.loads(response.model_dump_json())["result"]
    assert wire == json.loads(serialize_result(result))
    assert wire["at"] == "2026-10-07T19:00:00.000000Z"
    assert isinstance(response.result["at"], datetime)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_sql_wire_projection_preserves_native_instants_and_nulls(test_db, zone):
    from yoke_contracts.time_sql import instant_wire_sql
    from yoke_core.domain import db_helpers

    instant = parse_instant("2026-10-08T16:30:00.123456Z")
    with db_helpers.connect() as conn:
        conn.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
        row = conn.execute(
            f"SELECT {instant_wire_sql('%s::timestamptz')}, "
            f"{instant_wire_sql('NULL::timestamptz')}",
            (instant,),
        ).fetchone()
        assert row[0] == format_instant(instant)
        assert row[1] is None
        row = conn.execute(
            f"SELECT {instant_wire_sql('now()')}, "
            f"{instant_wire_sql('transaction_timestamp()')}"
        ).fetchone()
        assert row[0] == row[1]


def test_shared_typescript_sql_projection_is_generated_from_python():
    from pathlib import Path
    from yoke_contracts.time_sql import instant_wire_typescript

    root = Path(__file__).resolve().parents[3]
    contract = root / "packages/yoke-core/src/yoke_core/ui/contracts/time-sql.ts"
    assert contract.read_text() == instant_wire_typescript()
