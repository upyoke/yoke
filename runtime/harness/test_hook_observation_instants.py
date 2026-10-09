"""Resident observation and diagnostic boundaries retain exact native instants."""

from datetime import datetime, timezone
import json
import urllib.request

import pytest

from yoke_cli.transport.https_retry_policy import utc_stamp, write_retry_notice
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_harness import hook_observation_capture
from yoke_harness.hook_observation_delivery import owned_diagnostic_line
from yoke_harness.hook_observation_payload import PendingObservation
from yoke_harness.hook_resident_observations import (
    PendingObservation as QueuedObservation,
)
from yoke_harness.session_relay_failure_log import FailureReporter


QUALIFIED = "1970-01-01T05:44:59.123456+05:45"
CANONICAL = "1969-12-31T23:59:59.123456Z"
INSTANT = parse_instant(QUALIFIED)
OPAQUE = {"stdin": QUALIFIED, "model": "model-2026-10-08", "epoch": -0.876544}


def _pending(observed_at) -> PendingObservation:
    return PendingObservation(
        observation_id="observation-exact",
        endpoint="https://example.test/v1/hooks/telemetry/batch",
        authorization="Bearer test",
        observed_at=observed_at,
        hook_wait_ms=7,
        hook_request=OPAQUE,
        enqueued_at=12.5,
    )


@pytest.mark.parametrize("supplied", [QUALIFIED, INSTANT])
def test_pending_observation_keeps_native_clock_until_payload(supplied) -> None:
    pending = _pending(supplied)
    assert isinstance(pending.observed_at, datetime)
    assert pending.observed_at == INSTANT
    assert QueuedObservation is PendingObservation
    payload = json.loads(json.dumps(pending.payload()))
    assert payload == {
        "observation_id": "observation-exact",
        "observed_at": CANONICAL,
        "hook_wait_ms": 7,
        "hook_request": OPAQUE,
    }
    assert pending.enqueued_at == 12.5
    assert pending.hook_request is OPAQUE


@pytest.mark.parametrize(
    "supplied", [None, "", "1970-01-01", 0, False, datetime(1970, 1, 1)]
)
def test_pending_observation_refuses_unknown_or_implicit_clock(supplied) -> None:
    with pytest.raises(InvalidInstant):
        _pending(supplied)


def test_deferred_capture_uses_native_clock_and_canonical_payload(monkeypatch) -> None:
    monkeypatch.setattr(hook_observation_capture, "utc_now", lambda: INSTANT)
    opener = hook_observation_capture.DeferredObservationOpener()
    opener(
        urllib.request.Request(
            "https://example.test/v1/hooks/evaluate",
            data=json.dumps(OPAQUE).encode(),
            headers={"Authorization": "Bearer test"},
        )
    )
    observation = opener.observation(hook_wait_ms=7)
    assert observation.observed_at == INSTANT
    assert observation.payload()["observed_at"] == CANONICAL
    assert observation.payload()["hook_request"] == OPAQUE


@pytest.mark.parametrize("instant", [INSTANT, parse_instant(QUALIFIED)])
def test_owned_diagnostics_share_exact_fixed_six_utc(instant, capsys) -> None:
    assert utc_stamp(lambda: instant) == CANONICAL
    write_retry_notice("relay unreachable", 0, 1, clock=lambda: instant)
    assert capsys.readouterr().err.startswith(CANONICAL + " note:")
    line = owned_diagnostic_line(
        QUALIFIED,
        failure_class="transient_retry",
        outcome="retrying",
        clock=lambda: instant,
    )
    assert line.startswith(CANONICAL + " " + QUALIFIED)
    assert utc_stamp(lambda: datetime(1970, 1, 1, tzinfo=timezone.utc)) == (
        "1970-01-01T00:00:00.000000Z"
    )


@pytest.mark.parametrize(
    "supplied", [None, "", "1970-01-01", 0, False, datetime(1970, 1, 1)]
)
def test_bad_diagnostic_clock_refuses_before_log_or_failure_state(
    supplied, capsys
) -> None:
    with pytest.raises(InvalidInstant):
        write_retry_notice("relay unreachable", 0, 1, clock=lambda: supplied)
    assert capsys.readouterr().err == ""
    reporter = FailureReporter(stamp_clock=lambda: supplied)
    with pytest.raises(InvalidInstant):
        reporter.failed("poll", "offline")
    assert reporter.bursts == {}
    with pytest.raises(InvalidInstant):
        reporter.recovered("poll")
