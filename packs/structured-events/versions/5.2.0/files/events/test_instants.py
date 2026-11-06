"""Precise clocks, owned signed expiry, and no legacy payload admission."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from events import build_event
from events_cookie import AttributionCookie, COOKIE_NAME, _encode
from events_handoff import AttributionHandoff
from events_timestamps import InvalidInstant, format_instant, parse_instant, utc_now


def test_event_normalizes_offset_and_retains_all_microseconds():
    event = build_event(
        name="Viewed",
        kind="analytics",
        event_type="view",
        event_time="2026-10-08T05:30:00.123456+05:30",
        session_start_time="2026-10-08T00:00:00.000001Z",
    )
    assert event["event_time"] == "2026-10-08T00:00:00.123456Z"
    assert event["session_start_time"] == "2026-10-08T00:00:00.000001Z"


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30T00:00:00Z",
        "2026-10-08",
        "2026-10-08T00:00:00",
        "2026-10-08T00:00:00-00:00",
        "2026-10-08T00:00:00.1234567Z",
        datetime(2026, 10, 8),
    ],
)
def test_event_refuses_ambiguous_or_invalid_instants(value):
    with pytest.raises(InvalidInstant):
        build_event(
            name="Viewed", kind="analytics", event_type="view", event_time=value
        )


def test_handoff_callback_is_native_utc_and_output_is_canonical(monkeypatch):
    cookie = AttributionCookie("s" * 32, "example.com")
    record, header = cookie.capture("", "https://example.com", "")
    now = utc_now().replace(microsecond=123456)
    monkeypatch.setattr("events_handoff.utc_now", lambda: now)
    handoff = AttributionHandoff(cookie)
    minted = handoff.mint(header, "https://app.example.com")
    expected = now + timedelta(seconds=120)
    assert minted["expires_at"] == format_instant(expected)
    received = []
    redeemed, _ = handoff.redeem(
        minted["token"],
        "https://app.example.com",
        lambda nonce, expires: received.append(expires) or True,
    )
    assert redeemed == record and received == [expected]
    assert received[0].tzinfo == timezone.utc


def test_signed_legacy_numeric_cookie_is_discarded():
    cookie = AttributionCookie("s" * 32, "example.com")
    record, _ = cookie.capture("", "https://example.com", "")
    payload = _encode(json.dumps({"record": record, "expires": 9999999999}).encode())
    signature = _encode(
        hmac.new(cookie.secret, payload.encode(), hashlib.sha256).digest()
    )
    header = f"{COOKIE_NAME}={payload}.{signature}"
    with pytest.raises(ValueError, match="attribution_invalid"):
        cookie.read_verified(header)
    with pytest.warns(RuntimeWarning, match="attribution_cookie_reminted"):
        assert cookie.read(header) is None


def test_signed_legacy_numeric_handoff_never_consumes_nonce():
    cookie = AttributionCookie("s" * 32, "example.com")
    _, header = cookie.capture("", "https://example.com", "")
    handoff = AttributionHandoff(cookie)
    token = handoff.mint(header, "https://app.example.com")["token"]
    from events_cookie import _decode

    decoded = json.loads(_decode(token.split(".")[0]))
    decoded["expires"] = 9999999999
    payload = _encode(json.dumps(decoded).encode())
    signature = _encode(
        hmac.new(
            cookie.secret, ("attribution_handoff:" + payload).encode(), hashlib.sha256
        ).digest()
    )
    with pytest.raises(ValueError, match="attribution_handoff_invalid"):
        handoff.redeem(
            f"{payload}.{signature}",
            "https://app.example.com",
            lambda *args: pytest.fail("legacy payload touched durable nonce state"),
        )


def test_unknown_session_clock_remains_null():
    event = build_event(
        name="Viewed", kind="analytics", event_type="view", session_start_time=None
    )
    assert event["session_start_time"] is None
    assert parse_instant(event["event_time"]).tzinfo == timezone.utc
