"""The sealed browser-profile baseline path leaves stored Test Machine settings."""

import importlib
import json
import sqlite3

import pytest

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_settings,
)

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0070_remove_browser_profile_baseline_setting"
)
DECLARED = {
    "resource_name": "test-mac",
    "host": "test-mac.local",
    "user": "qa",
    "os": "macos",
    "operating_notes": "",
    "golden_baseline_path": "/Users/Shared/goldens/qa-golden",
}


def database(*rows):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY, type TEXT, settings TEXT)"
    )
    for index, (cap_type, document) in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO project_capabilities VALUES (?, ?, ?)",
            (index, cap_type, json.dumps(document)),
        )
    return conn


def settings(conn, row_id):
    return json.loads(
        conn.execute(
            "SELECT settings FROM project_capabilities WHERE id = ?", (row_id,)
        ).fetchone()[0]
    )


def test_the_baseline_path_is_removed_and_every_other_setting_kept():
    retired = {**DECLARED, "browser_profile_baseline_path": "/Users/Shared/goldens/p"}
    browser = {"browser_profile_baseline_path": "not a test machine"}
    conn = database(("test-machine:test-mac", retired), ("browser-control", browser))
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    assert settings(conn, 1) == DECLARED
    assert settings(conn, 2) == browser
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before


def test_converged_settings_validate_and_the_key_is_refused():
    conn = database(
        ("test-machine:test-mac", {**DECLARED, MIGRATION.RETIRED_SETTING: "/x"})
    )
    MIGRATION.apply(conn)
    validate_test_machine_settings(settings(conn, 1))
    with pytest.raises(
        TestMachineCapabilityError, match="unknown browser_profile_baseline_path"
    ):
        validate_test_machine_settings({**DECLARED, MIGRATION.RETIRED_SETTING: "/x"})


def test_invalid_document_names_recovery():
    conn = database(("test-machine:test-mac", []))
    with pytest.raises(RuntimeError, match="test_machine_settings_invalid.*Recovery:"):
        MIGRATION.apply(conn)


def test_remaining_setting_fails_the_invariant():
    conn = database(("test-machine:test-mac", {MIGRATION.RETIRED_SETTING: "/x"}))
    with pytest.raises(
        AssertionError, match="browser_profile_baseline_setting_remains"
    ):
        MIGRATION.invariants(conn)


def test_serving_floor_is_the_carrying_release():
    assert MIGRATION.MINIMUM_SERVING_VERSION == "next-release"
