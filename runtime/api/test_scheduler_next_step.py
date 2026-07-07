"""Type-aware next-step routing tests for yoke_core.domain.scheduler."""
from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.scheduler import (
    NextStep,
    _compute_next_step,
)
from yoke_core.domain.frontier import AdapterCategory


class TestComputeNextStep:
    """Verify type-aware next-step mapping."""

    # -- Issue-workflow-type: refine --
    def test_issue_idea_maps_to_refine(self):
        result = _compute_next_step("issue", "idea", AdapterCategory.REFINE)
        assert result.next_step == NextStep.REFINE

    def test_issue_refining_idea_maps_to_refine(self):
        result = _compute_next_step("issue", "refining-idea", AdapterCategory.REFINE)
        assert result.next_step == NextStep.REFINE

    # -- Issue-workflow-type: advance — AC-12, AC-20 --
    def test_issue_refined_idea_maps_to_advance(self):
        result = _compute_next_step("issue", "refined-idea", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.ADVANCE

    def test_issue_implementing_maps_to_advance(self):
        result = _compute_next_step("issue", "implementing", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.ADVANCE

    def test_issue_reviewing_implementation_maps_to_advance(self):
        result = _compute_next_step("issue", "reviewing-implementation", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.ADVANCE

    # -- Issue-workflow-type: polish --
    def test_issue_reviewed_implementation_maps_to_polish(self):
        result = _compute_next_step("issue", "reviewed-implementation", AdapterCategory.POLISH)
        assert result.next_step == NextStep.POLISH

    def test_issue_polishing_implementation_maps_to_polish(self):
        result = _compute_next_step("issue", "polishing-implementation", AdapterCategory.POLISH)
        assert result.next_step == NextStep.POLISH

    # -- Issue-workflow-type: usher --
    def test_issue_implemented_maps_to_usher(self):
        result = _compute_next_step("issue", "implemented", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    def test_issue_release_maps_to_usher(self):
        result = _compute_next_step("issue", "release", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    # -- Epic-workflow-type: explicit routing --
    def test_epic_idea_maps_to_refine(self):
        """AC-1: epic idea -> refine."""
        result = _compute_next_step("epic", "idea", AdapterCategory.SHEPHERD)
        assert result.next_step == NextStep.REFINE

    def test_epic_refining_idea_maps_to_refine(self):
        """AC-1: epic refining-idea -> refine."""
        result = _compute_next_step("epic", "refining-idea", AdapterCategory.REFINE)
        assert result.next_step == NextStep.REFINE

    def test_epic_refined_idea_maps_to_shepherd(self):
        """AC-2: epic refined-idea -> shepherd."""
        result = _compute_next_step("epic", "refined-idea", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.SHEPHERD

    def test_epic_planning_maps_to_shepherd(self):
        """AC-3: epic planning -> shepherd."""
        result = _compute_next_step("epic", "planning", AdapterCategory.SHEPHERD)
        assert result.next_step == NextStep.SHEPHERD

    def test_epic_plan_drafted_maps_to_refine(self):
        """epic plan-drafted -> refine."""
        result = _compute_next_step("epic", "plan-drafted", AdapterCategory.REFINE)
        assert result.next_step == NextStep.REFINE

    def test_epic_refining_plan_maps_to_refine(self):
        """AC-4: epic refining-plan -> refine."""
        result = _compute_next_step("epic", "refining-plan", AdapterCategory.REFINE)
        assert result.next_step == NextStep.REFINE

    def test_epic_planned_maps_to_conduct(self):
        """AC-5: epic planned -> conduct."""
        result = _compute_next_step("epic", "planned", AdapterCategory.SHEPHERD)
        assert result.next_step == NextStep.CONDUCT

    def test_epic_implementing_maps_to_conduct(self):
        """AC-6: epic implementing -> conduct."""
        result = _compute_next_step("epic", "implementing", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.CONDUCT

    def test_epic_reviewing_implementation_maps_to_conduct(self):
        """epic reviewing-implementation -> conduct."""
        result = _compute_next_step("epic", "reviewing-implementation", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.CONDUCT

    def test_epic_reviewed_implementation_maps_to_polish(self):
        """epic reviewed-implementation -> polish."""
        result = _compute_next_step("epic", "reviewed-implementation", AdapterCategory.POLISH)
        assert result.next_step == NextStep.POLISH

    def test_epic_polishing_implementation_maps_to_polish(self):
        """AC-7: epic polishing-implementation -> polish."""
        result = _compute_next_step("epic", "polishing-implementation", AdapterCategory.POLISH)
        assert result.next_step == NextStep.POLISH

    def test_epic_implemented_maps_to_usher(self):
        """AC-8: epic implemented -> usher."""
        result = _compute_next_step("epic", "implemented", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    def test_epic_release_maps_to_usher(self):
        """epic release -> usher."""
        result = _compute_next_step("epic", "release", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    def test_epic_in_defined_maps_to_shepherd(self):
        """Legacy status defined -> falls through to default adapter (SHEPHERD)."""
        result = _compute_next_step("epic", "defined", AdapterCategory.SHEPHERD)
        assert result.next_step == NextStep.SHEPHERD

    # -- Shared/legacy statuses on issues -> ADVANCE (AC-20: conduct rejects issues) --
    def test_issue_in_ready_maps_to_advance(self):
        result = _compute_next_step("issue", "ready", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.ADVANCE

    def test_issue_in_active_maps_to_advance(self):
        result = _compute_next_step("issue", "active", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.ADVANCE

    def test_issue_in_review_maps_to_advance(self):
        result = _compute_next_step("issue", "review", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.ADVANCE

    def test_issue_in_passed_maps_to_usher(self):
        result = _compute_next_step("issue", "passed", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    def test_issue_in_validate_maps_to_usher(self):
        result = _compute_next_step("issue", "validate", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    def test_blocked_maps_to_wait(self):
        result = _compute_next_step("issue", "blocked", AdapterCategory.WAIT)
        assert result.next_step == NextStep.WAIT

    # -- Epic-workflow-type routing via _EPIC_ADAPTER_MAP --
    def test_epic_active_maps_to_conduct_legacy(self):
        """Legacy status active -> falls through to default adapter (CONDUCT)."""
        result = _compute_next_step("epic", "active", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.CONDUCT

    def test_epic_review_maps_to_conduct_legacy(self):
        """Legacy status review -> falls through to default adapter (CONDUCT)."""
        result = _compute_next_step("epic", "review", AdapterCategory.CONDUCT)
        assert result.next_step == NextStep.CONDUCT

    def test_epic_passed_maps_to_usher_legacy(self):
        """Legacy status passed -> falls through to default adapter (USHER)."""
        result = _compute_next_step("epic", "passed", AdapterCategory.USHER)
        assert result.next_step == NextStep.USHER

    # -- T7 AC-6: Refine/polish status advance on success only --
    def test_refine_does_not_produce_advance_step(self):
        """AC-6: refine step is REFINE, not ADVANCE — status advance is skill-level."""
        result = _compute_next_step("issue", "idea", AdapterCategory.REFINE)
        assert result.next_step == NextStep.REFINE
        assert result.next_step != NextStep.ADVANCE

    def test_polish_does_not_produce_advance_step(self):
        """AC-6: polish step is POLISH, not ADVANCE — status advance is skill-level."""
        result = _compute_next_step("issue", "polishing-implementation", AdapterCategory.POLISH)
        assert result.next_step == NextStep.POLISH
        assert result.next_step != NextStep.ADVANCE


class TestAdvanceFeasibilityProbeRewrite:
    """YOK-1779: (issue, refined-idea, advance) is rewritten to refine
    when the candidate's planned path-claim would activate INCOMPATIBLE
    against a non-terminal sibling. After the operator authors a
    coordination_only `item_dependencies` edge, the rewrite no longer
    fires and the step returns ADVANCE.
    """

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
        actor_id INTEGER NOT NULL REFERENCES actors(id),
        session_id TEXT REFERENCES harness_sessions(session_id),
        item_id INTEGER, integration_target TEXT NOT NULL,
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
    -- Full column set from `schema_init_actor_path_claim_tables`: the
    -- override reader selects every column, and on Postgres a
    -- missing-column error would abort the probe's transaction.
    CREATE TABLE path_claim_overrides (
        id INTEGER PRIMARY KEY, path_claim_id INTEGER NOT NULL,
        blocking_claim_id INTEGER,
        blocking_path_targets TEXT NOT NULL DEFAULT '[]',
        override_point TEXT, conflict_reason TEXT, integration_target TEXT,
        actor_id INTEGER, actor_reason TEXT, item_id INTEGER,
        project TEXT, session_id TEXT, created_at TEXT
    );
    -- Required by the probe's transitive call into classify_overlap →
    -- _is_render_target_only_overlap → read_render_source_for →
    -- read_context_value. Canonical DDL lives in
    -- `yoke_core.domain.schema_init_path_tables.create_path_registry_tables`.
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
        for cid, item in ((500, 42), (501, 43)):
            conn.execute(
                "INSERT INTO path_claims (id, state, mode, actor_id, item_id, "
                "integration_target, registered_at) "
                "VALUES (%s, 'planned', 'exclusive', 1, %s, 'main', "
                "'2026-05-19T00:00:00Z')",
                (cid, item),
            )
            conn.execute(
                "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
                "VALUES (%s, 100, '2026-05-19T00:00:00Z')",
                (cid,),
            )

    def test_blocked_overlap_rewrites_to_refine(self):
        from yoke_core.domain.scheduler_routing import (
            ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED,
        )
        conn = self._make_db()
        self._seed(conn)
        try:
            result = _compute_next_step(
                "issue", "refined-idea", AdapterCategory.CONDUCT,
                conn=conn, item_id=42,
            )
            assert result.next_step == NextStep.REFINE
            assert result.routing_override is not None
            assert result.routing_override.reason == ROUTING_OVERRIDE_PATH_CLAIM_BLOCKED
            assert result.routing_override.original_step == NextStep.ADVANCE.value
            assert "YOK-43" in result.routing_override.conflicting_item_ids
            assert "shared.py" in result.routing_override.shared_paths
        finally:
            conn.close()

    def test_coordination_only_edge_unblocks(self):
        conn = self._make_db()
        self._seed(conn)
        for dep, block in ((42, 43), (43, 42)):
            conn.execute(
                "INSERT INTO item_dependencies "
                "(dependent_item, blocking_item, gate_point, satisfaction, "
                "source, rationale, created_at) "
                "VALUES (%s, %s, 'coordination_only', 'compatible', 'agent', "
                "'compatible same-path edits', '2026-05-19T00:00:00Z')",
                (dep, block),
            )
        try:
            result = _compute_next_step(
                "issue", "refined-idea", AdapterCategory.CONDUCT,
                conn=conn, item_id=42,
            )
            assert result.next_step == NextStep.ADVANCE
            assert result.routing_override is None
        finally:
            conn.close()

    def test_other_triples_pass_through_when_conn_supplied(self):
        """conn + item_id supplied for a non-(issue, refined-idea, advance)
        triple — probe MUST NOT fire."""
        conn = self._make_db()
        # No schema needed — the probe never runs.
        result = _compute_next_step(
            "issue", "implementing", AdapterCategory.CONDUCT,
            conn=conn, item_id=99,
        )
        conn.close()
        assert result.next_step == NextStep.ADVANCE
        assert result.routing_override is None
