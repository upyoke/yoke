"""Retention cutoffs keep fractional precision and pending dispatch custody."""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_helpers, function_call_ledger as ledger
from yoke_core.domain import github_workflow_dispatch_intents as intents

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_ledger_expiration_is_strict_at_native_microsecond_cutoff(
    test_db, monkeypatch, zone
):
    test_db.execute(ledger.FUNCTION_CALL_LEDGER_CREATE_SQL)
    monkeypatch.setattr(ledger, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    cutoff = STAMP - timedelta(days=ledger.LEDGER_TTL_DAYS)
    for name, stamp in [
        ("before", cutoff - timedelta(microseconds=1)),
        ("at", cutoff),
        ("after", cutoff + timedelta(microseconds=1)),
    ]:
        assert ledger.record_call(
            name,
            "clock.read",
            {},
            actor_id="2",
            authorization_scope="project:1",
            payload_checksum=name,
            created_at=stamp,
            conn=test_db,
        )
    assert ledger.count_expired(test_db) == 1
    assert ledger.prune_expired(test_db) == 1
    remaining = test_db.execute(
        "SELECT request_id, created_at FROM function_call_ledger ORDER BY created_at"
    ).fetchall()
    assert [tuple(row) for row in remaining] == [
        ("at", cutoff),
        ("after", cutoff + timedelta(microseconds=1)),
    ]


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_dispatch_birth_and_terminal_retention_use_native_clocks(
    test_db, monkeypatch, zone
):
    test_db.execute(intents.GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL)
    monkeypatch.setattr(intents, "utc_now", lambda: STAMP)

    @contextmanager
    def connect():
        yield test_db

    monkeypatch.setattr(db_helpers, "connect", connect)
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    for name in ["pending", "before", "at"]:
        assert intents.claim_attempt(
            request_id=name,
            attempt=1,
            actor_id="2",
            authorization_scope="project:1",
            payload_checksum=name,
            repo="upyoke/yoke",
            workflow="check.yml",
            workflow_ref="main",
            inputs={},
            correlation_id=name,
        )
    assert all(
        tuple(row) == (STAMP, STAMP)
        for row in test_db.execute(
            "SELECT created_at, updated_at FROM github_workflow_dispatch_intents"
        ).fetchall()
    )
    cutoff = STAMP - timedelta(days=intents.INTENT_TTL_DAYS)
    for name, state, stamp in [
        ("pending", "pending", cutoff - timedelta(microseconds=1)),
        ("before", "rejected", cutoff - timedelta(microseconds=1)),
        ("at", "rejected", cutoff),
    ]:
        test_db.execute(
            "UPDATE github_workflow_dispatch_intents SET state=%s, updated_at=%s WHERE request_id=%s",
            (state, stamp, name),
        )
    assert intents.count_expired(test_db) == 1
    assert intents.prune_expired(test_db) == 1
    assert [
        row[0]
        for row in test_db.execute(
            "SELECT request_id FROM github_workflow_dispatch_intents ORDER BY request_id"
        ).fetchall()
    ] == ["at", "pending"]


@pytest.mark.parametrize("value", ["", "2026-10-08T12:34:56", datetime(2026, 10, 8), 1])
def test_retention_cutoffs_refuse_unqualified_supplied_clock(value):
    for owner in [ledger, intents]:
        with pytest.raises(ValueError):
            owner.ttl_cutoff_iso(value)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_client_completion_lookup_keeps_exact_inclusive_window(
    test_db, monkeypatch, zone
):
    import json

    from runtime.api.fixtures.backlog import insert_event
    from yoke_core.domain import hook_client_wall

    monkeypatch.setattr(hook_client_wall, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    cutoff = STAMP - hook_client_wall.PENDING_DELIVERY_WINDOW
    for name, stamp in [("at", cutoff), ("before", cutoff - timedelta(microseconds=1))]:
        insert_event(
            test_db,
            event_id=name,
            created_at=stamp,
            client_timing_id=name,
            envelope=json.dumps({"context": {"client_timing_id": name}}),
        )
    assert hook_client_wall._matching_event(test_db, "at") is not None
    assert hook_client_wall._matching_event(test_db, "before") is None
