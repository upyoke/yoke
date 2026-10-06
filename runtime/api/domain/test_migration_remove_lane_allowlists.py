"""Stored routing documents converge to groupings without losing custom lanes."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

from yoke_core.domain.session_routing_validation import (
    validate_session_routing_settings,
)

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0054_remove_lane_allowlists"
)

LEVEL_RENAME = importlib.import_module(
    "yoke_core.domain.migrations.0057_rename_session_lanes_to_levels"
)


def converged_to_levels(settings):
    """Apply the later lanes -> levels rename the live validator reads."""
    return LEVEL_RENAME._converged(1, settings)


def database(settings, *, capability="session-routing"):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY, type TEXT, settings TEXT)"
    )
    conn.execute(
        "INSERT INTO project_capabilities VALUES (1, ?, ?)",
        (capability, json.dumps(settings)),
    )
    return conn


def stored(conn):
    return json.loads(
        conn.execute("SELECT settings FROM project_capabilities").fetchone()[0]
    )


def test_grouped_and_flat_permissions_are_removed_preserving_routing():
    settings = {
        "lane_paths": {"DARIUS": ["dash"], "CUSTOM": []},
        "lane_paths_altman": "refine,polish",
        "lane_metadata": {"CUSTOM": {"label": "CUSTOM", "glyph": "🚀"}},
        "executor_default_lanes": {"claude*": "DARIUS", "codex*": "ALTMAN"},
        "lane_rules": [{"model": "gpt-*", "lane": "CUSTOM"}],
        "max_chain_steps": 3,
    }
    conn = database(settings)
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    result = stored(conn)
    assert "lane_paths" not in result and "lane_paths_altman" not in result
    for key in ("executor_default_lanes", "lane_rules", "max_chain_steps"):
        assert result[key] == settings[key]
    assert result["lane_metadata"]["CUSTOM"] == settings["lane_metadata"]["CUSTOM"]
    assert set(result["lane_metadata"]) == {"DARIUS", "ALTMAN", "CUSTOM"}
    validate_session_routing_settings(converged_to_levels(result))
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before


def test_lane_declared_only_by_permissions_becomes_metadata_grouping():
    conn = database(
        {"lane_paths": {"CUSTOM": []}, "executor_default_lanes": {"cursor*": "CUSTOM"}}
    )
    MIGRATION.apply(conn)
    result = stored(conn)
    assert result["lane_metadata"]["CUSTOM"]["label"] == "CUSTOM"
    validate_session_routing_settings(converged_to_levels(result))


def test_already_converged_and_other_capabilities_are_untouched():
    for settings, capability in [
        ({"lane_metadata": {"CUSTOM": {"label": "CUSTOM"}}}, "session-routing"),
        ({"lane_paths": {"CUSTOM": []}}, "another-capability"),
    ]:
        conn = database(settings, capability=capability)
        before = conn.total_changes
        MIGRATION.apply(conn)
        MIGRATION.invariants(conn)
        assert stored(conn) == settings
        assert conn.total_changes == before


def test_missing_capability_table_is_safe():
    conn = sqlite3.connect(":memory:")
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)


@pytest.mark.parametrize("settings", [[], {"lane_metadata": []}])
def test_malformed_document_refuses_with_recovery(settings):
    with pytest.raises(
        RuntimeError, match="session_routing_document_invalid.*Recovery:"
    ):
        MIGRATION.apply(database(settings))


def test_invariants_detect_residual_permissions():
    with pytest.raises(AssertionError, match="lane_action_allowlists_remain"):
        MIGRATION.invariants(database({"lane_paths_CUSTOM": "dash"}))


def test_data_cutover_declares_next_serving_build():
    assert MIGRATION.MINIMUM_SERVING_VERSION == "next-release"
