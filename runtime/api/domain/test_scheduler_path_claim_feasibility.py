"""Unit tests for :mod:`yoke_core.domain.scheduler_path_claim_feasibility`.

Covers the five cases the spec enumerates: no overlap, INCOMPATIBLE
with planned sibling, terminal sibling claim, coordination_only edge,
and missing candidate claim.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.scheduler_path_claim_feasibility import (
    FeasibilityOutcome,
    probe_advance_feasibility,
)


# Minimal schema needed for the probe + classify_overlap dependency walk.
# Kept here so the test file is self-contained without needing the
# Yoke schema migrator wiring.
_SCHEMA = """
CREATE TABLE actors (
    id INTEGER PRIMARY KEY,
    name TEXT
);
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY
);
CREATE TABLE path_targets (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    path_string TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1,
    parent_target_id INTEGER,
    created_at TEXT NOT NULL,
    materialization_state TEXT NOT NULL DEFAULT 'observed'
);
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'planned',
    mode TEXT NOT NULL DEFAULT 'exclusive',
    actor_id INTEGER NOT NULL REFERENCES actors(id),
    session_id TEXT REFERENCES harness_sessions(session_id),
    item_id INTEGER,
    integration_target TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    activated_at TEXT,
    released_at TEXT,
    cancelled_at TEXT
);
CREATE TABLE path_claim_targets (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES path_claims(id),
    target_id INTEGER NOT NULL REFERENCES path_targets(id),
    declared_at TEXT NOT NULL
);
CREATE TABLE item_dependencies (
    id INTEGER PRIMARY KEY,
    dependent_item INTEGER,
    blocking_item INTEGER,
    gate_point TEXT,
    satisfaction TEXT,
    source TEXT,
    rationale TEXT,
    created_at TEXT
);
CREATE TABLE path_claim_overrides (
    id INTEGER PRIMARY KEY,
    path_claim_id INTEGER NOT NULL,
    blocking_claim_id INTEGER,
    blocking_path_targets TEXT NOT NULL DEFAULT '[]',
    override_point TEXT NOT NULL,
    conflict_reason TEXT,
    integration_target TEXT,
    actor_id INTEGER,
    actor_reason TEXT NOT NULL,
    item_id INTEGER,
    project TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL
);
-- Required by the probe's transitive call into classify_overlap →
-- _is_render_target_only_overlap → read_render_source_for →
-- read_context_value. Canonical DDL lives in
-- `yoke_core.domain.schema_init_path_tables.create_path_registry_tables`.
CREATE TABLE path_context_values (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL,
    context_family TEXT NOT NULL,
    entry_key TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '{}',
    recorded_event_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(c, _SCHEMA)
    c.execute("INSERT INTO actors (id, name) VALUES (1, 'tester')")
    yield c
    c.close()


def _insert_target(conn, target_id, path_string, parent=None):
    conn.execute(
        "INSERT INTO path_targets "
        "(id, project_id, kind, path_string, generation, parent_target_id, "
        "created_at, materialization_state) "
        "VALUES (%s, 1, 'file', %s, 1, %s, '2026-05-19T00:00:00Z', 'observed')",
        (target_id, path_string, parent),
    )


def _insert_claim(conn, claim_id, item_id, state, *, integration_target="main"):
    conn.execute(
        "INSERT INTO path_claims "
        "(id, state, mode, actor_id, item_id, integration_target, registered_at) "
        "VALUES (%s, %s, 'exclusive', 1, %s, %s, '2026-05-19T00:00:00Z')",
        (claim_id, state, item_id, integration_target),
    )


def _attach_target(conn, claim_id, target_id):
    conn.execute(
        "INSERT INTO path_claim_targets "
        "(claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-19T00:00:00Z')",
        (claim_id, target_id),
    )


class TestNoCandidateClaim:
    """Item with no planned/active path claim returns no_claim — the
    readiness gate owns that diagnostic, the probe passes through."""

    def test_no_claim_outcome(self, conn) -> None:
        verdict = probe_advance_feasibility(conn, item_id=42)
        assert verdict.outcome is FeasibilityOutcome.NO_CLAIM
        assert verdict.candidate_claim_id is None
        assert "no planned path-claim" in verdict.reason


class TestFeasibleNoOverlap:
    """Single planned claim, no siblings on the same integration target
    → feasible."""

    def test_feasible_when_alone(self, conn) -> None:
        _insert_target(conn, 100, "a.py")
        _insert_claim(conn, 500, item_id=42, state="planned")
        _attach_target(conn, 500, 100)
        verdict = probe_advance_feasibility(conn, item_id=42)
        assert verdict.outcome is FeasibilityOutcome.FEASIBLE
        assert verdict.candidate_claim_id == 500


class TestBlockedCrossItemOverlap:
    """Two items both hold planned exclusive claims on the same path
    target with no item_dependencies edge → blocked."""

    def test_blocked_when_sibling_planned(self, conn) -> None:
        _insert_target(conn, 100, "shared.py")
        _insert_claim(conn, 500, item_id=42, state="planned")
        _attach_target(conn, 500, 100)
        _insert_claim(conn, 501, item_id=43, state="planned")
        _attach_target(conn, 501, 100)
        verdict = probe_advance_feasibility(conn, item_id=42)
        assert verdict.outcome is FeasibilityOutcome.BLOCKED_CROSS_ITEM_OVERLAP
        assert verdict.candidate_claim_id == 500
        assert 501 in verdict.conflicting_claim_ids
        assert "YOK-43" in verdict.conflicting_item_ids
        assert "shared.py" in verdict.shared_paths


class TestTerminalSiblingIgnored:
    """A released or cancelled sibling claim does not contribute to the
    overlap — terminal claims are excluded from the non-terminal set
    the probe walks."""

    def test_released_sibling_does_not_block(self, conn) -> None:
        _insert_target(conn, 100, "shared.py")
        _insert_claim(conn, 500, item_id=42, state="planned")
        _attach_target(conn, 500, 100)
        _insert_claim(conn, 501, item_id=43, state="released")
        _attach_target(conn, 501, 100)
        verdict = probe_advance_feasibility(conn, item_id=42)
        assert verdict.outcome is FeasibilityOutcome.FEASIBLE


class TestCoordinationOnlyFeasible:
    """A coordination_only item_dependencies edge between the two items
    attests the overlap is compatible — classify_overlap treats it as
    parallel-safe, so the probe returns feasible."""

    def test_coordination_only_edge_makes_feasible(self, conn) -> None:
        _insert_target(conn, 100, "shared.py")
        _insert_claim(conn, 500, item_id=42, state="planned")
        _attach_target(conn, 500, 100)
        _insert_claim(conn, 501, item_id=43, state="planned")
        _attach_target(conn, 501, 100)
        # Author the coordination_only edge in both directions so the
        # classifier finds the attestation regardless of which item is
        # the candidate-as-DEPENDENT side.
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, "
            "source, rationale, created_at) "
            "VALUES (42, 43, 'coordination_only', 'compatible', "
            "'agent', 'independent edits on the same path', "
            "'2026-05-19T00:00:00Z')",
        )
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction, "
            "source, rationale, created_at) "
            "VALUES (43, 42, 'coordination_only', 'compatible', "
            "'agent', 'independent edits on the same path', "
            "'2026-05-19T00:00:00Z')",
        )
        verdict = probe_advance_feasibility(conn, item_id=42)
        assert verdict.outcome is FeasibilityOutcome.FEASIBLE
