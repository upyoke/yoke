"""Operation models retain native clocks until their declared output owners."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain.coordination_claim_contention import ClaimContention, _age_seconds
from yoke_core.domain.deployment_run_terminalization import RunTerminalization
from yoke_core.domain.web_sessions import CreatedWebSession
from yoke_core.domain.strategy_docs_ingest import IngestDocPlan, dry_run_report

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


def ingest_plan(clock):
    return IngestDocPlan(
        "MISSION", Path("MISSION.md"), clock, clock, "body", True, 1, 1, 4, 4
    )


MODELS = [
    (contention, "acquired_at"),
    (terminalization, "terminalized_at"),
    (web_session, "expires_at"),
    (ingest_plan, "base_updated_at"),
]


@pytest.mark.parametrize("factory,field", MODELS)
@pytest.mark.parametrize(
    "clock",
    [
        INSTANT,
        INSTANT.astimezone(timezone(timedelta(hours=5, minutes=30))),
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
    report = contention(
        INSTANT, INSTANT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    )
    assert report.heartbeat_at == INSTANT
    evidence = report.claim_evidence()
    assert (
        evidence["acquired_at"] == evidence["heartbeat_at"] == format_instant(INSTANT)
    )
    assert "since " + format_instant(INSTANT) in report.message
    assert contention(INSTANT).claim_evidence()["heartbeat_at"] is None


def test_ingest_plan_compares_native_clocks_and_formats_conflict_report():
    plan = IngestDocPlan(
        "MISSION",
        Path("MISSION.md"),
        "1970-01-01T05:29:59.123456+05:30",
        INSTANT,
        "body",
        True,
        1,
        1,
        4,
        4,
    )
    assert plan.base_updated_at == plan.db_updated_at == INSTANT
    assert not plan.stale_base
    newer = IngestDocPlan(
        "MISSION",
        Path("MISSION.md"),
        INSTANT,
        INSTANT + timedelta(microseconds=1),
        "body",
        True,
        1,
        1,
        4,
        4,
    )
    assert newer.stale_base
    report = dry_run_report([newer])[0]
    assert report["status"] == "conflict"
    assert report["base_updated_at"] == format_instant(INSTANT)
    assert report["db_updated_at"] == format_instant(
        INSTANT + timedelta(microseconds=1)
    )


@pytest.mark.parametrize("factory", [contention, terminalization])
@pytest.mark.parametrize(
    "wire", ["1969-12-31T23:59:59.123456Z", "1970-01-01T05:29:59.123456+05:30"]
)
def test_internal_operation_model_refuses_qualified_wire_clock(factory, wire):
    with pytest.raises(InvalidInstant):
        factory(wire)
    with pytest.raises(InvalidInstant):
        contention(INSTANT, wire)


def test_contention_age_floors_exact_seconds_across_valid_years():
    earliest = datetime(1, 1, 1, tzinfo=timezone.utc)
    latest = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert _age_seconds(earliest, latest) == 315537897599
    assert (
        _age_seconds(INSTANT, INSTANT + timedelta(seconds=600, microseconds=-1)) == 599
    )
    assert _age_seconds(INSTANT, INSTANT + timedelta(seconds=600)) == 600
    assert _age_seconds(INSTANT + timedelta(microseconds=1), INSTANT) == 0
    assert _age_seconds(None, INSTANT) is None


@pytest.mark.parametrize(
    "factory,field", [(web_session, "expires_at"), (ingest_plan, "base_updated_at")]
)
def test_operation_ingress_models_parse_their_owned_qualified_wire_clock(
    factory, field
):
    assert getattr(factory("1970-01-01T05:29:59.123456+05:30"), field) == INSTANT
