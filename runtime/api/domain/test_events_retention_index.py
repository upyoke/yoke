"""The events retention index is born, rebuilt concurrently and serves prune."""

import importlib

import pytest

from yoke_contracts.schema_authority import serving_build_authority
from yoke_core.domain.events_retention_index import (
    RETENTION_INDEX_NAME,
    NAME_RETENTION_INDEX_NAME,
    RETENTION_INDEX_SPECS,
    ensure_retention_index,
    verify_retention_index,
)

migration = importlib.import_module(
    "yoke_core.domain.migrations.0080_events_retention_index"
)


@pytest.mark.parametrize("name", [spec[0] for spec in RETENTION_INDEX_SPECS])
def test_born_schema_carries_index_and_migration_rebuilds_it(test_db, name):
    verify_retention_index(test_db)
    test_db.execute(f"DROP INDEX {name}")
    test_db.commit()
    with pytest.raises(RuntimeError, match="events_retention_index_not_ready"):
        verify_retention_index(test_db)
    # A concurrent build waits for every open transaction, including ours.
    test_db.rollback()
    with serving_build_authority():
        migration.apply(test_db)
        ensure_retention_index(test_db)
    migration.invariants(test_db)


@pytest.mark.parametrize("name", [spec[0] for spec in RETENTION_INDEX_SPECS])
def test_differently_defined_index_refuses_rebuild(test_db, name):
    test_db.execute(f"DROP INDEX {name}")
    test_db.execute(f"CREATE INDEX {name} ON events(created_at)")
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


def test_name_migration_replaces_old_index_and_preserves_rows(test_db):
    from runtime.api.fixtures.backlog import insert_event

    replacement = importlib.import_module(
        "yoke_core.domain.migrations.0097_events_name_retention_index"
    )
    insert_event(test_db, event_id="preserved")
    test_db.execute(f"DROP INDEX {NAME_RETENTION_INDEX_NAME}")
    test_db.execute("CREATE INDEX idx_events_event_name ON events(event_name)")
    test_db.commit()
    with serving_build_authority():
        replacement.apply(test_db)
        replacement.apply(test_db)
    replacement.invariants(test_db)
    assert test_db.execute(
        "SELECT event_id FROM events"
    ).fetchall() == [("preserved",)]


def test_each_name_override_reads_its_composite_range(test_db):
    from yoke_contracts.timestamps import utc_now
    from yoke_contracts.universe_retention import RetentionPolicy
    from yoke_core.domain.retention_table_policies import policies

    policy = RetentionPolicy()
    rule = policies(policy, utc_now())[0]
    test_db.execute("SET enable_seqscan=off")
    for where, params in rule.branches[:len(policy.event_days)]:
        plan = "\n".join(
            row[0] for row in test_db.execute(
                "EXPLAIN SELECT t.id FROM events t WHERE " + where
                + " ORDER BY t.created_at LIMIT 5001", params
            ).fetchall()
        )
        assert NAME_RETENTION_INDEX_NAME in plan, plan
        assert "Index Cond:" in plan and "event_name =" in plan, plan
        assert "created_at <" in plan, plan
    # Name-only callers retain an index path after the obsolete index is gone.
    plan = "\n".join(row[0] for row in test_db.execute(
        "EXPLAIN SELECT id FROM events WHERE event_name='OrdinaryEvent'"
    ).fetchall())
    assert NAME_RETENTION_INDEX_NAME in plan, plan
    test_db.rollback()
