"""Authority equality ignores telemetry; real authority changes still land.

Telemetry is disposable: an event emitted, pruned, or never written between
two receipts of the same universe is not a change of authority. These tests
pin that boundary from both sides — churn must not move the digest, and a
genuine data or schema change must still move it.
"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg

from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)
from yoke_core.domain.source_authority_receipts import authority_receipt
from yoke_core.domain.source_freeze_intent import freeze_intent


@contextmanager
def _canonical_test_universe():
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn

    name = pg_testdb.create_test_database()
    dsn = pg_testdb.dsn_for_test_database(name)
    try:
        run_init_chain_at_dsn(dsn, emit=lambda _line: None)
        with psycopg.connect(dsn) as conn:
            yield conn
    finally:
        pg_testdb.drop_test_database(name)


def _emit(conn, event_id: str, name: str = "TelemetryChurn") -> None:
    conn.execute(
        "INSERT INTO events (event_id, source_type, session_id, event_kind,"
        " event_type, event_name, envelope, created_at)"
        " VALUES (%s, 'script', 'telemetry-churn-session', 'system',"
        " 'test.telemetry', %s, %s, now())",
        (event_id, name, '{"context":{}}'),
    )


def _intent(conn, authority):
    return freeze_intent(
        database={"database": "src", "database_oid": 7, "org": "yoke"},
        frozen_at="2026-07-14T00:00:00Z",
        authority=authority,
        archive={"sha256": "a" * 64, "bytes": 4096, "catalog_digest": "c" * 64},
        zero_writable_app_sessions=False,
    )


def test_telemetry_is_absent_from_the_authority_comparison():
    with _canonical_test_universe() as conn:
        _emit(conn, "seed-1")
        conn.commit()
        receipt = authority_receipt(conn, include_content_digests=True)

    assert "events" not in receipt["tables"]
    assert "events" not in receipt["portable_table_catalog"]
    assert "event_max_created_at" not in receipt
    assert receipt["normalization"]["excluded_table_ownership"][
        "disposable_telemetry"
    ] == ["events"]
    assert not [
        entry for entry in receipt["sequences"] if entry["owner_table"] == "events"
    ]
    # Event SCHEMA is still proven: the table stays in the full database
    # catalog, which is what a missing or renamed events table would move.
    assert "events" in receipt["database_table_catalog"]


def test_emitting_pruning_and_never_emitting_all_yield_one_digest():
    with _canonical_test_universe() as conn:
        _emit(conn, "before-1")
        _emit(conn, "before-2")
        conn.commit()
        with_events = authority_receipt(conn, include_content_digests=True)

        # Churn: new rows, an advanced sequence, and a failed emission that
        # left nothing behind.
        _emit(conn, "churn-1")
        _emit(conn, "churn-2")
        conn.commit()
        after_churn = authority_receipt(conn, include_content_digests=True)

        # Retention: everything the pruner could ever remove.
        conn.execute("DELETE FROM events")
        conn.commit()
        pruned_empty = authority_receipt(conn, include_content_digests=True)

    assert after_churn["receipt_digest"] == with_events["receipt_digest"]
    assert pruned_empty["receipt_digest"] == with_events["receipt_digest"]


def test_freeze_intent_is_telemetry_free_and_stable_across_churn():
    with _canonical_test_universe() as conn:
        _emit(conn, "intent-1")
        conn.commit()
        before = _intent(conn, authority_receipt(conn))

        _emit(conn, "intent-2")
        conn.execute("DELETE FROM events WHERE event_id = 'intent-1'")
        conn.commit()
        after = _intent(conn, authority_receipt(conn))

    assert "event_watermark" not in before
    assert before["schema"] == "yoke.source-freeze/v2"
    assert after["receipt_id"] == before["receipt_id"]


def test_real_data_change_still_moves_the_authority_digest():
    with _canonical_test_universe() as conn:
        before = authority_receipt(conn, include_content_digests=True)
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix,"
            " created_at) VALUES (88001, 'portable', 'Portable', 'POR', now())"
        )
        conn.commit()
        after = authority_receipt(conn, include_content_digests=True)

    assert after["receipt_digest"] != before["receipt_digest"]


def test_real_schema_change_to_events_still_moves_the_fingerprint():
    with _canonical_test_universe() as conn:
        before = authority_receipt(conn)
        before_fingerprint = fingerprint_portable_postgres_schema(conn)
        conn.execute("ALTER TABLE events ADD COLUMN smuggled_column TEXT")
        conn.commit()
        after = authority_receipt(conn)

    assert after["schema_fingerprint"] != before_fingerprint
    assert after["receipt_digest"] != before["receipt_digest"]
