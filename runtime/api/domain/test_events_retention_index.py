"""The events retention index is born, rebuilt concurrently and serves prune."""

import importlib

import pytest

from yoke_contracts.schema_authority import serving_build_authority
from yoke_core.domain.events_retention_index import (
    BOOTSTRAP_AUDIT_RECORD,
    RETENTION_INDEX_NAME,
    ensure_retention_index,
    verify_retention_index,
)

migration = importlib.import_module(
    "yoke_core.domain.migrations.0078_events_retention_index"
)


def _receipts(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM migration_audit WHERE migration_name=%s",
        (BOOTSTRAP_AUDIT_RECORD["name"],),
    ).fetchone()[0]


def test_born_schema_carries_index_and_migration_rebuilds_it_once(test_db):
    verify_retention_index(test_db)
    test_db.execute(f"DROP INDEX {RETENTION_INDEX_NAME}")
    test_db.commit()
    with pytest.raises(RuntimeError, match="events_retention_index_not_ready"):
        verify_retention_index(test_db)
    # A concurrent build waits for every open transaction, including ours.
    test_db.rollback()
    with serving_build_authority():
        migration.apply(test_db)
        ensure_retention_index(test_db)
    migration.invariants(test_db)
    assert _receipts(test_db) == 1


def test_differently_defined_index_refuses_rebuild(test_db):
    test_db.execute(f"DROP INDEX {RETENTION_INDEX_NAME}")
    test_db.execute(f"CREATE INDEX {RETENTION_INDEX_NAME} ON events(created_at)")
    test_db.commit()
    with serving_build_authority():
        with pytest.raises(RuntimeError, match="definition_mismatch"):
            ensure_retention_index(test_db)


def test_severity_slice_reads_the_index_range(test_db):
    test_db.execute("SET enable_seqscan=off")
    plan = "\n".join(
        row[0]
        for row in test_db.execute(
            "EXPLAIN SELECT t.id FROM events t WHERE t.severity='DEBUG' "
            "AND t.created_at<now() ORDER BY t.created_at LIMIT 10"
        ).fetchall()
    )
    test_db.rollback()
    assert RETENTION_INDEX_NAME in plan
