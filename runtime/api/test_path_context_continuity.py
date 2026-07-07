"""Focused tests for path continuity and path-context reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain import path_continuity, path_context
from runtime.api.path_context_test_helpers import (
    NOW,
    emit_event,
    init_minimal_schema,
    mint_target,
)


@pytest.fixture
def conn(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    c = init_minimal_schema(db_path)
    yield c
    c.close()


class TestContinuityRecording:
    def test_workflow_observed_move_records_row(self, conn):
        before = mint_target(conn, "yoke", "old/path.py")
        after = mint_target(conn, "yoke", "new/path.py")
        event_id = emit_event(conn, name="WorkflowObservedMove")
        move_id = path_continuity.record_workflow_observed_move(
            conn,
            before_target_id=before,
            after_target_id=after,
            recorded_event_id=event_id,
        )
        row = conn.execute(
            "SELECT before_target_id, after_target_id, recorded_event_id "
            "FROM path_moves WHERE id=%s",
            (move_id,),
        ).fetchone()
        assert (row[0], row[1], row[2]) == (before, after, event_id)

    def test_operator_adjudicated_move_records_row(self, conn):
        before = mint_target(conn, "yoke", "old/path.py")
        after = mint_target(conn, "yoke", "new/path.py")
        event_id = emit_event(conn, name="OperatorAdjudicatedMove")
        move_id = path_continuity.record_operator_adjudicated_move(
            conn,
            before_target_id=before,
            after_target_id=after,
            recorded_event_id=event_id,
        )
        row = conn.execute(
            "SELECT recorded_event_id FROM path_moves WHERE id=%s",
            (move_id,),
        ).fetchone()
        assert row[0] == event_id

    def test_writer_refuses_empty_provenance_string(
        self, conn,
    ):
        """recorded_event_id is opaque (no ledger FK check — retention
        prunes events the durable row outlives) but stays mandatory."""
        before = mint_target(conn, "yoke", "old/path.py")
        after = mint_target(conn, "yoke", "new/path.py")
        with pytest.raises(
            path_continuity.PathContinuityError,
            match="non-empty provenance string",
        ):
            path_continuity.record_workflow_observed_move(
                conn,
                before_target_id=before,
                after_target_id=after,
                recorded_event_id="   ",
            )

    def test_writer_accepts_pruned_event_id(self, conn):
        """A provenance id absent from the (retention-pruned) ledger is
        accepted — the string is opaque provenance, not a live FK."""
        before = mint_target(conn, "yoke", "old/path.py")
        after = mint_target(conn, "yoke", "new/path.py")
        move_id = path_continuity.record_workflow_observed_move(
            conn,
            before_target_id=before,
            after_target_id=after,
            recorded_event_id="evt-pruned-long-ago",
        )
        assert move_id > 0

    def test_writer_refuses_same_before_after(self, conn):
        target = mint_target(conn, "yoke", "self/path.py")
        event_id = emit_event(conn)
        with pytest.raises(
            path_continuity.PathContinuityError,
            match="distinct before/after",
        ):
            path_continuity.record_workflow_observed_move(
                conn,
                before_target_id=target,
                after_target_id=target,
                recorded_event_id=event_id,
            )


class TestNearestAncestorInheritance:
    def test_value_inherited_from_parent(self, conn):
        root = mint_target(conn, "yoke", "", kind="directory")
        directory = mint_target(
            conn,
            "yoke",
            "src",
            kind="directory",
            parent_target_id=root,
        )
        leaf = mint_target(conn, "yoke", "src/foo.py", parent_target_id=directory)
        event_id = emit_event(conn)
        path_context.put_context_value(
            conn,
            target_id=directory,
            context_family="posture",
            entry_key="criticality",
            value={"level": "high"},
            recorded_event_id=event_id,
        )
        assert path_context.read_context_value(
            conn,
            target_id=leaf,
            context_family="posture",
            entry_key="criticality",
        ) == {"level": "high"}

    def test_nearer_ancestor_wins(self, conn):
        root = mint_target(conn, "yoke", "", kind="directory")
        directory = mint_target(
            conn,
            "yoke",
            "src",
            kind="directory",
            parent_target_id=root,
        )
        nested = mint_target(
            conn,
            "yoke",
            "src/sub",
            kind="directory",
            parent_target_id=directory,
        )
        leaf = mint_target(conn, "yoke", "src/sub/foo.py", parent_target_id=nested)
        event_id = emit_event(conn)
        path_context.put_context_value(
            conn,
            target_id=directory,
            context_family="posture",
            entry_key="criticality",
            value={"level": "low"},
            recorded_event_id=event_id,
        )
        path_context.put_context_value(
            conn,
            target_id=nested,
            context_family="posture",
            entry_key="criticality",
            value={"level": "high"},
            recorded_event_id=event_id,
        )
        assert path_context.read_context_value(
            conn,
            target_id=leaf,
            context_family="posture",
            entry_key="criticality",
        ) == {"level": "high"}

    def test_no_value_returns_none(self, conn):
        leaf = mint_target(conn, "yoke", "untouched.py")
        assert path_context.read_context_value(
            conn,
            target_id=leaf,
            context_family="posture",
            entry_key="criticality",
        ) is None


def test_same_depth_conflict_synthetic():
    """Bypass the live UNIQUE constraint to exercise AC-8's conflict path."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        apply_fixture_ddl(
            conn,
            """
            CREATE TABLE path_targets (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                path_string TEXT NOT NULL,
                generation INTEGER NOT NULL,
                parent_target_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE path_context_values (
                id INTEGER PRIMARY KEY,
                target_id INTEGER NOT NULL,
                context_family TEXT NOT NULL,
                entry_key TEXT NOT NULL DEFAULT '',
                value TEXT NOT NULL DEFAULT '{}',
                recorded_event_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            """,
        )
        root = mint_target(conn, "yoke", "", kind="directory")
        mid = mint_target(
            conn, "yoke", "mid", kind="directory", parent_target_id=root
        )
        leaf = mint_target(conn, "yoke", "mid/leaf.py", parent_target_id=mid)
        for value in ('{"level": "low"}', '{"level": "high"}'):
            conn.execute(
                "INSERT INTO path_context_values "
                "(target_id, context_family, entry_key, value, "
                "recorded_event_id, recorded_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (mid, "posture", "criticality", value, "ev1", NOW),
            )
        conn.commit()

        with pytest.raises(
            path_context.PathContextConflictError,
            match="same-depth conflict",
        ):
            path_context.read_context_value(
                conn,
                target_id=leaf,
                context_family="posture",
                entry_key="criticality",
            )
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


class TestArchitectureFamilyConstants:
    """architecture-fitness adds nine architecture-fitness family constants.

    The constants partition into classification (layer/domain/dependency
    rule/cross-cutting entrypoint) and exemption (generated/fixture/
    archive/test_surface/template_managed) sets. Both reuse the existing
    ``put_context_value`` / ``read_context_value`` surface; no new writer.
    """

    def test_classification_constants_present(self):
        assert path_context.FAMILY_ARCHITECTURE_LAYER == "architecture_layer"
        assert path_context.FAMILY_ARCHITECTURE_DOMAIN == "architecture_domain"
        assert (
            path_context.FAMILY_DEPENDENCY_RULE
            == "architecture_dependency_rule"
        )
        assert (
            path_context.FAMILY_CROSS_CUTTING_ENTRYPOINT
            == "architecture_cross_cutting_entrypoint"
        )

    def test_exemption_constants_present(self):
        assert path_context.FAMILY_GENERATED == "architecture_generated"
        assert path_context.FAMILY_FIXTURE == "architecture_fixture"
        assert path_context.FAMILY_ARCHIVE == "architecture_archive"
        assert path_context.FAMILY_TEST_SURFACE == "architecture_test_surface"
        assert (
            path_context.FAMILY_TEMPLATE_MANAGED
            == "architecture_template_managed"
        )

    def test_known_families_includes_architecture(self):
        assert (
            path_context.ARCHITECTURE_FAMILIES
            <= path_context.KNOWN_FAMILIES
        )

    def test_classification_and_exemption_disjoint(self):
        assert (
            path_context.ARCHITECTURE_CLASSIFICATION_FAMILIES
            & path_context.ARCHITECTURE_EXEMPTION_FAMILIES
            == frozenset()
        )

    def test_layer_value_inherits_through_existing_reader(
        self, conn
    ):
        """Architecture families piggyback on the existing inherited reader.

        ``path_context_values`` supports architecture context families
        using the existing inherited context reader. This is just a smoke
        check that the new family name flows end-to-end through the
        unchanged writer/reader.
        """
        parent = mint_target(
            conn, "yoke", "runtime/api/domain", kind="directory"
        )
        child = mint_target(
            conn, "yoke", "runtime/api/domain/path_claims.py",
            parent_target_id=parent,
        )
        event_id = emit_event(conn, name="ArchitectureLayerAssigned")
        path_context.put_context_value(
            conn,
            target_id=parent,
            context_family=path_context.FAMILY_ARCHITECTURE_LAYER,
            entry_key="",
            value={"layer": "domain_invariants"},
            recorded_event_id=event_id,
        )
        conn.commit()
        inherited = path_context.read_context_value(
            conn,
            target_id=child,
            context_family=path_context.FAMILY_ARCHITECTURE_LAYER,
            entry_key="",
        )
        assert inherited == {"layer": "domain_invariants"}
