"""Ordered migration coverage for converging project level copies."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

from yoke_contracts.levels import default_levels, levels_payload
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.session_routing_validation import (
    validate_session_routing_settings,
)

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0062_converge_levels_to_universe"
)

# The copy every project carried before levels became universe settings.
SEEDED_COPY = {
    "executor_default_levels": {"claude*": "DARIUS", "codex*": "ALTMAN"},
    "executor_default_level_cursor": "DARIUS",
    "level_metadata": {"DARIUS": {"label": "DARIUS", "glyph": "\U0001f40e"}},
    "level_rules": [{"model": "gpt-*", "level": "ALTMAN"}],
}
OVERRIDE = {"levels": levels_payload(default_levels()[:1])}


def _database(*rows) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE project_capabilities "
        "(id INTEGER PRIMARY KEY, type TEXT, settings TEXT)"
    )
    for row_id, capability, settings in rows:
        conn.execute(
            "INSERT INTO project_capabilities VALUES (?, ?, ?)",
            (row_id, capability, json.dumps(settings)),
        )
    return conn


def _stored(conn) -> dict:
    return {
        row_id: json.loads(settings)
        for row_id, settings in conn.execute(
            "SELECT id, settings FROM project_capabilities ORDER BY id"
        )
    }


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(MIGRATION) == NEXT_RELEASE


def test_seeded_copies_are_removed_and_overrides_kept() -> None:
    conn = _database(
        (1, "session-routing", SEEDED_COPY),
        (2, "session-routing", {**SEEDED_COPY, **OVERRIDE}),
        (3, "session-routing", {}),
        (4, "project-policy", {"level_metadata": {"kept": True}}),
    )

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert _stored(conn) == {2: OVERRIDE, 4: {"level_metadata": {"kept": True}}}
    validate_session_routing_settings(_stored(conn)[2])
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before


def test_a_converged_document_is_what_the_write_boundary_accepts() -> None:
    assert MIGRATION.converged(SEEDED_COPY) == {}
    validate_session_routing_settings(MIGRATION.converged({**SEEDED_COPY, **OVERRIDE}))


def test_an_unreadable_document_refuses_with_recovery() -> None:
    conn = _database()
    conn.execute(
        "INSERT INTO project_capabilities VALUES (1, 'session-routing', '[1]')"
    )
    with pytest.raises(RuntimeError, match="session_routing_document_invalid"):
        MIGRATION.apply(conn)


def test_invariants_name_a_document_still_carrying_retired_keys() -> None:
    conn = _database((1, "session-routing", SEEDED_COPY))
    with pytest.raises(AssertionError, match="level_metadata"):
        MIGRATION.invariants(conn)
