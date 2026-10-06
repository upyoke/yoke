"""Unused process policy converges without altering session routing."""

import importlib
import json
import sqlite3

import pytest

from yoke_core.domain.session_routing_validation import (
    SessionRoutingSettingsError,
    validate_session_routing_settings,
)

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0055_remove_process_offer_settings"
)


def database(settings, capability="session-routing"):
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


def test_all_policy_shapes_converge_preserving_unrelated_settings():
    retained = {
        "executor_default_lanes": {"codex*": "CUSTOM"},
        "lane_metadata": {"CUSTOM": {"label": "CUSTOM"}},
        "lane_rules": [{"model": "gpt-*", "lane": "CUSTOM"}],
        "max_chain_steps": 3,
    }
    conn = database(
        {
            **retained,
            "process_offers": {"feed": True},
            "process_offer": {"default": False},
            "do_process_offer_doctor": "true",
        }
    )
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    assert stored(conn) == retained
    validate_session_routing_settings(stored(conn))
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before


@pytest.mark.parametrize(
    "key", ["process_offer", "process_offers", "do_process_offer_feed"]
)
def test_writers_refuse_removed_policy_with_recovery(key):
    with pytest.raises(
        SessionRoutingSettingsError, match="process_offer_policy_retired: remove"
    ):
        validate_session_routing_settings({key: {}})


def test_other_capabilities_and_converged_documents_are_untouched():
    for settings, capability in [
        ({}, "session-routing"),
        ({"process_offers": {}}, "other"),
    ]:
        conn = database(settings, capability)
        before = conn.total_changes
        MIGRATION.apply(conn)
        MIGRATION.invariants(conn)
        assert stored(conn) == settings
        assert conn.total_changes == before


def test_missing_table_is_safe():
    conn = sqlite3.connect(":memory:")
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)


def test_invalid_document_refuses_with_recovery():
    with pytest.raises(
        RuntimeError, match="session_routing_document_invalid.*Recovery:"
    ):
        MIGRATION.apply(database([]))


def test_remaining_policy_is_an_invariant_failure():
    with pytest.raises(AssertionError, match="process_offer_policy_remains"):
        MIGRATION.invariants(database({"process_offers": {}}))


def test_data_cutover_declares_next_serving_build():
    assert MIGRATION.MINIMUM_SERVING_VERSION == "next-release"
