"""Fleet tuning is removed idempotently while organization choices survive."""

import importlib
import json
import sqlite3

import pytest

from yoke_contracts.organization_contract.fleet_keys import merge_fleet_settings

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0065_remove_fleet_settings"
)


def database(document):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE organizations (id INTEGER PRIMARY KEY, settings TEXT)")
    conn.execute("INSERT INTO organizations VALUES (1, ?)", (json.dumps(document),))
    return conn


def test_tuning_is_removed_without_altering_membership():
    retained = {"membership": {"auto_join_domain_verified": True}}
    conn = database(
        {
            **retained,
            "fleet": {"launch_deadline_minutes": 30},
            "fleet.max_body_bytes": 123,
        }
    )
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    assert (
        json.loads(conn.execute("SELECT settings FROM organizations").fetchone()[0])
        == retained
    )
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before


def test_old_membership_migration_can_run_before_tuning_removal():
    # Permanent history merges the membership choice before this later removal.
    document, _ = merge_fleet_settings(
        {"fleet": {"relay_poll_seconds": 30}},
        {"membership": {"auto_join_domain_verified": True}},
    )
    conn = database(document)
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)


def test_removed_keys_cannot_be_written():
    with pytest.raises(ValueError, match="unknown organization setting"):
        merge_fleet_settings({}, {"fleet": {"relay_poll_seconds": 30}})


def test_invalid_document_names_recovery():
    with pytest.raises(RuntimeError, match="organization_settings_invalid.*Recovery:"):
        MIGRATION.apply(database([]))


def test_remaining_tuning_fails_the_invariant():
    with pytest.raises(AssertionError, match="fleet_settings_remain"):
        MIGRATION.invariants(database({"fleet": {}}))


def test_serving_floor_is_the_carrying_release():
    assert MIGRATION.MINIMUM_SERVING_VERSION == "next-release"
