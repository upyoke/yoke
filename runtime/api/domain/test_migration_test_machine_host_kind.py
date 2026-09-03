"""Convergence coverage for the declared test-machine host kind."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

from yoke_contracts.machine_config.test_machine import (
    MAC_SSH_HOST_KIND,
    validate_test_machine_settings,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0037_test_machine_host_kind"
)
MACHINE = "mac-mini-lab"
MACHINE_TYPE = f"test-machine:{MACHINE}"


def _settings(**overrides: str) -> str:
    document = {
        "resource_name": MACHINE,
        "host": "test-mac.local",
        "user": "yoke-test",
        "operating_notes": "",
        **overrides,
    }
    return json.dumps(document, separators=(",", ":"), sort_keys=True)


def _database(
    settings: str, *, capability_type: str = MACHINE_TYPE
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}',
            verified_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, type)
        );
        """
    )
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "VALUES(1,?,?,'2026-01-01T00:00:00Z')",
        (capability_type, settings),
    )
    conn.commit()
    return conn


def _stored(conn: sqlite3.Connection) -> dict[str, str]:
    row = conn.execute(
        "SELECT settings FROM project_capabilities WHERE type=?",
        (MACHINE_TYPE,),
    ).fetchone()
    return json.loads(row["settings"])


def test_every_registered_machine_gains_the_kind_it_already_was() -> None:
    # Every machine registered before this entry is reached over SSH to a
    # macOS host, because that is the only implementation the product has had.
    conn = _database(_settings())

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    document = _stored(conn)
    assert document["host_kind"] == MAC_SSH_HOST_KIND
    # The converged document is exactly what the live contract accepts.
    assert validate_test_machine_settings(document) == document


def test_applying_twice_changes_nothing_the_first_apply_did_not() -> None:
    # A database restored from a pre-ledger archive replays its history.
    conn = _database(_settings())

    MIGRATION.apply(conn)
    once = _stored(conn)
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert _stored(conn) == once


def test_an_optional_golden_baseline_survives_the_convergence() -> None:
    conn = _database(
        _settings(golden_baseline_path="/Users/Shared/yoke-golden/tester-home")
    )

    MIGRATION.apply(conn)

    document = _stored(conn)
    assert document["golden_baseline_path"] == "/Users/Shared/yoke-golden/tester-home"
    assert document["host_kind"] == MAC_SSH_HOST_KIND


def test_a_kind_nobody_implements_stops_the_boot_rather_than_being_rewritten() -> None:
    conn = _database(_settings(host_kind="linux-ssh"))

    with pytest.raises(ValueError) as refused:
        MIGRATION.apply(conn)

    assert "declares unknown host_kind" in str(refused.value)


def test_unreadable_settings_name_the_row_to_repair() -> None:
    conn = _database("not json at all")

    with pytest.raises(ValueError) as refused:
        MIGRATION.apply(conn)

    assert MACHINE_TYPE in str(refused.value)
    assert "repair the row" in str(refused.value)


def test_the_entry_declares_the_build_that_may_serve_against_it() -> None:
    # The settings contract refuses unknown keys, so a build written before
    # this entry reports the whole capability invalid rather than ignoring one
    # field.
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE


def test_a_database_with_no_capability_table_converges_to_nothing() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
