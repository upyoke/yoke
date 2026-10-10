"""Operation models retain native clocks until their declared output owners."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain.coordination_claim_contention import ClaimContention
from yoke_core.domain.deployment_run_terminalization import RunTerminalization
from yoke_core.domain.web_sessions import CreatedWebSession

INSTANT = parse_instant("1969-12-31T23:59:59.123456Z")


def contention(clock, heartbeat=None):
    return ClaimContention(
        1,
        2,
        "shared-operation",
        "holder",
        clock,
        heartbeat,
        None,
        10,
        False,
        "operator recovery",
    )


def terminalization(clock):
    return RunTerminalization(
        "run",
        "project",
        "executing",
        "failed",
        "reason",
        clock,
        None,
        "session",
        "event",
    )


def web_session(clock):
    return CreatedWebSession(1, 2, "opaque-token", clock)


MODELS = [
    (contention, "acquired_at"),
    (terminalization, "terminalized_at"),
    (web_session, "expires_at"),
]


@pytest.mark.parametrize("factory,field", MODELS)
@pytest.mark.parametrize(
    "clock",
    [
        INSTANT,
        INSTANT.astimezone(timezone(timedelta(hours=5, minutes=30))),
        "1970-01-01T05:29:59.123456+05:30",
    ],
)
def test_operation_clock_is_native_and_normalized(factory, field, clock):
    model = factory(clock)
    assert getattr(model, field) == INSTANT
    assert getattr(model, field).tzinfo is timezone.utc


@pytest.mark.parametrize("factory,field", MODELS)
@pytest.mark.parametrize(
    "bad",
    [
        datetime(1970, 1, 1),
        "then",
        "1970-01-01",
        "1970-01-01T00:00:00-00:00",
        "1970-01-01T00:00:00.1234567Z",
    ],
)
def test_operation_model_rejects_ambiguous_clock(factory, field, bad):
    with pytest.raises(InvalidInstant):
        factory(bad)


def test_contention_evidence_formats_only_at_the_output_owner():
    report = contention(INSTANT, "1970-01-01T05:29:59.123456+05:30")
    assert report.heartbeat_at == INSTANT
    evidence = report.claim_evidence()
    assert (
        evidence["acquired_at"] == evidence["heartbeat_at"] == format_instant(INSTANT)
    )
    assert "since " + format_instant(INSTANT) in report.message
    assert contention(INSTANT).claim_evidence()["heartbeat_at"] is None
