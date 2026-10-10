"""Function request JSON owns native clocks without rewriting opaque strings."""

from datetime import date, datetime, timedelta, timezone
import json

import pytest
from pydantic_core import PydanticSerializationError

from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    FakeResponse,
    envelope,
    sensitive_request,
)
from yoke_cli.transport import https as relay
from yoke_contracts.timestamps import format_instant, parse_instant

CLOCKS = [
    parse_instant("1970-01-01T00:00:00Z"),
    datetime(1970, 1, 1, 5, 29, 59, 123456, timezone(timedelta(hours=5, minutes=30))),
    parse_instant("1969-12-31T23:59:59.123456Z"),
    datetime(2024, 2, 29, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
]
FIELDS = ["payload", "preconditions", "options"]
OPAQUE = "historical text 2026-01-01T00:00:00+05:30"


def _add_clocks(request, field, clock):
    getattr(request, field).update(
        {
            "clock": clock,
            "nested": {"clock": clock, "unknown": None},
            "opaque": OPAQUE,
            "day": date(2024, 2, 29),
            "duration_seconds": 3,
        }
    )


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("clock", CLOCKS)
def test_request_keeps_native_python_values_until_owned_json(field, clock):
    request = sensitive_request()
    _add_clocks(request, field, clock)
    native = request.model_dump()[field]
    assert isinstance(native["clock"], datetime)
    assert native["clock"] == clock
    assert native["clock"].utcoffset() == clock.utcoffset()
    for wire in [
        request.model_dump(mode="json"),
        json.loads(request.model_dump_json()),
    ]:
        projected = wire[field]
        assert projected["clock"] == format_instant(clock)
        assert projected["nested"] == {"clock": format_instant(clock), "unknown": None}
        assert projected["opaque"] == OPAQUE
        assert projected["day"] == "2024-02-29"
        assert projected["duration_seconds"] == 3


@pytest.mark.parametrize("clock", CLOCKS)
def test_https_adapter_sends_fixed_six_utc_native_clocks(monkeypatch, clock):
    sent = []
    request = sensitive_request()
    for field in FIELDS:
        _add_clocks(request, field, clock)

    def open_relay(outbound, **kwargs):
        sent.append(json.loads(outbound.data))
        return FakeResponse(envelope(result={"ok": True}))

    monkeypatch.setattr(relay, "_open_function_relay", open_relay)
    monkeypatch.setattr(relay, "record_outcome", lambda *args, **kwargs: None)
    assert relay.relay_https(request, CONNECTION).success
    assert len(sent) == 1
    for field in FIELDS:
        assert sent[0][field]["clock"] == format_instant(clock)
        assert sent[0][field]["opaque"] == OPAQUE
    assert isinstance(request.payload["clock"], datetime)


@pytest.mark.parametrize("field", FIELDS)
def test_request_json_refuses_a_naive_native_clock_with_named_recovery(field):
    request = sensitive_request()
    _add_clocks(request, field, datetime(1970, 1, 1))
    with pytest.raises(
        PydanticSerializationError,
        match="invalid_instant: supply a valid RFC3339 timestamp",
    ):
        request.model_dump_json()
