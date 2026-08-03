"""Definition-selected next-step routing tests."""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.frontier import AdapterCategory
from yoke_core.domain.scheduler import NextStep, _compute_next_step


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (AdapterCategory.REFINE, NextStep.REFINE),
        (AdapterCategory.SHEPHERD, NextStep.SHEPHERD),
        (AdapterCategory.CONDUCT, NextStep.CONDUCT),
        (AdapterCategory.ADVANCE, NextStep.ADVANCE),
        (AdapterCategory.BLITZ, NextStep.BLITZ),
        (AdapterCategory.DASH, NextStep.DASH),
        (AdapterCategory.POLISH, NextStep.POLISH),
        (AdapterCategory.USHER, NextStep.USHER),
        (AdapterCategory.WAIT, NextStep.WAIT),
        (AdapterCategory.SKIP, NextStep.WAIT),
    ],
)
def test_registered_adapter_maps_to_scheduler_step(adapter, expected):
    result = _compute_next_step(adapter)
    assert result.next_step is expected


class TestAdvanceFeasibilityProbeRewrite:
    """Definition-selected item-claim activation may reroute to refine."""

    _SCHEMA = """
    CREATE TABLE actors (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT);
    CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY);
    CREATE TABLE path_targets (
        id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
        path_string TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 1,
        parent_target_id INTEGER, created_at TEXT NOT NULL,
        materialization_state TEXT NOT NULL DEFAULT 'observed'
    );
    CREATE TABLE path_claims (
        id INTEGER PRIMARY KEY, state TEXT NOT NULL DEFAULT 'planned',
        mode TEXT NOT NULL DEFAULT 'exclusive',
        owner_kind TEXT, owner_item_id INTEGER, owner_session_id TEXT,
        owner_work_claim_id INTEGER, registered_by_actor_id INTEGER,
        registered_by_session_id TEXT, integration_target TEXT NOT NULL,
        registered_at TEXT NOT NULL, activated_at TEXT,
        released_at TEXT, cancelled_at TEXT
    );
    CREATE TABLE path_claim_targets (
        id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL, declared_at TEXT NOT NULL
    );
    CREATE TABLE item_dependencies (
        id INTEGER PRIMARY KEY, dependent_item INTEGER, blocking_item INTEGER,
        gate_point TEXT, satisfaction TEXT, source TEXT, rationale TEXT,
        created_at TEXT
    );
    CREATE TABLE path_claim_overrides (
        id INTEGER PRIMARY KEY, path_claim_id INTEGER NOT NULL,
        blocking_claim_id INTEGER,
        blocking_path_targets TEXT NOT NULL DEFAULT '[]',
        override_point TEXT, conflict_reason TEXT, integration_target TEXT,
        actor_id INTEGER, actor_reason TEXT, item_id INTEGER,
        project TEXT, session_id TEXT, created_at TEXT
    );
    CREATE TABLE path_context_values (
        id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL,
        context_family TEXT NOT NULL, entry_key TEXT NOT NULL DEFAULT '',
        value TEXT NOT NULL DEFAULT '{}',
        recorded_event_id TEXT NOT NULL, recorded_at TEXT NOT NULL
    );
    """

    def _make_db(self):
        name = pg_testdb.create_test_database()
        return pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name,
        )

    def _seed(self, conn):
        apply_fixture_ddl(conn, self._SCHEMA)
        conn.execute("INSERT INTO actors (id, name) VALUES (1, 'tester')")
        conn.execute(
            "INSERT INTO path_targets (id, project_id, kind, path_string, "
            "generation, parent_target_id, created_at, materialization_state) "
            "VALUES (100, 'yoke', 'file', 'shared.py', 1, NULL, "
            "'2026-05-19T00:00:00Z', 'observed')"
        )
        for claim_id, item_id in ((500, 42), (501, 43)):
            conn.execute(
                "INSERT INTO path_claims (id, state, mode, owner_kind, owner_item_id, "
                "registered_by_actor_id, integration_target, registered_at) "
                "VALUES (%s, 'planned', 'exclusive', 'item', %s, 1, 'main', "
                "'2026-05-19T00:00:00Z')",
                (claim_id, item_id),
            )
            conn.execute(
                "INSERT INTO path_claim_targets "
                "(claim_id, target_id, declared_at) "
                "VALUES (%s, 100, '2026-05-19T00:00:00Z')",
                (claim_id,),
            )

    def test_blocked_overlap_rewrites_to_refine(self):
        from yoke_core.domain.scheduler_routing import (
            ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED,
        )

        conn = self._make_db()
        self._seed(conn)
        try:
            result = _compute_next_step(
                AdapterCategory.ADVANCE,
                probe_path_claim_activation=True,
                conn=conn,
                item_id=42,
            )
            assert result.next_step is NextStep.REFINE
            assert result.routing_override is not None
            assert (
                result.routing_override.reason
                == ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED
            )
            assert "YOK-43" in result.routing_override.conflicting_item_ids
            assert "shared.py" in result.routing_override.shared_paths
        finally:
            conn.close()

    def test_coordination_only_edge_unblocks(self):
        conn = self._make_db()
        self._seed(conn)
        for dependent, blocking in ((42, 43), (43, 42)):
            conn.execute(
                "INSERT INTO item_dependencies "
                "(dependent_item, blocking_item, gate_point, satisfaction, "
                "source, rationale, created_at) "
                "VALUES (%s, %s, 'coordination_only', 'compatible', 'agent', "
                "'compatible same-path edits', '2026-05-19T00:00:00Z')",
                (dependent, blocking),
            )
        try:
            result = _compute_next_step(
                AdapterCategory.ADVANCE,
                probe_path_claim_activation=True,
                conn=conn,
                item_id=42,
            )
            assert result.next_step is NextStep.ADVANCE
            assert result.routing_override is None
        finally:
            conn.close()

    def test_probe_is_not_run_without_definition_signal(self):
        conn = self._make_db()
        result = _compute_next_step(
            AdapterCategory.ADVANCE,
            conn=conn,
            item_id=99,
        )
        conn.close()
        assert result.next_step is NextStep.ADVANCE
        assert result.routing_override is None
