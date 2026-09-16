"""Unit tests for :mod:`yoke_core.domain.path_claim_register`.

The overlap-denial body embeds the conflicting claim
id(s), the overlapping path strings, and the
``yoke claims path coordination-decision-build`` command shape so the operator's
next move is one paste.
"""

from __future__ import annotations

from yoke_contracts.public_ref import unresolved_item_ref
from yoke_core.domain.path_claim_register import compose_overlap_denial

# The denial composes with no connection under these tests, so there is no
# identity to read and nothing to name the item by.
UNREADABLE_INTERNAL_ID = 123


class TestComposeOverlapDenialNoConflicts:
    """When the conflict scan finds no rows (e.g. conn=None under unit
    tests), the body names the integration target and emits the
    resolution-command template with placeholders so the contract shape
    is visible. With no connection there is no identity read, so the item
    position says it could not resolve one rather than minting a ref out
    of the storage key the caller passed."""

    def test_includes_header_and_resolution_command(self) -> None:
        body = compose_overlap_denial(
            item_id=UNREADABLE_INTERNAL_ID,
            integration_target="main",
            candidate_target_ids=[],
            base_message="overlap reason text",
            conn=None,
        )
        assert "BLOCKED: path-claim register overlap" in body
        assert unresolved_item_ref(consulted=False) in body
        assert str(UNREADABLE_INTERNAL_ID) not in body
        assert "integration_target='main'" in body
        assert "overlap reason text" in body
        assert "yoke claims path coordination-decision-build" in body
        assert f"--item {unresolved_item_ref(consulted=False)}" in body

    def test_no_conflicts_uses_placeholder_claim_id(self) -> None:
        body = compose_overlap_denial(
            item_id=42,
            integration_target="main",
            candidate_target_ids=[],
            base_message="reason",
            conn=None,
        )
        # No live claim id -> placeholder shown so the operator knows
        # what to substitute.
        assert "<claim-id>" in body
        assert "<paths>" in body


# The overlapping item's public sequence is its own counter, so a denial
# that printed the internal id would name a different item to the reader.
PROJECT_ID = 1
ITEM_PREFIX = "YOK"
OVERLAP_INTERNAL_ID = 42
OVERLAP_SEQUENCE = 17


class TestComposeOverlapDenialWithConflicts:
    """With a live disposable-Postgres connection and conflicting claims,
    the body enumerates each conflicting claim id with its overlapping
    paths and emits the resolution command pointed at the first conflict."""

    def test_enumerates_conflicts_and_paths(self, tmp_path) -> None:
        from runtime.api.fixtures import pg_testdb
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
        from yoke_core.domain.path_claims_overlap import (
            OverlapClassification,
        )

        name = pg_testdb.create_test_database()
        conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name
        )
        # Minimal schema needed by _blocking_conflicts_for + the inline
        # path_strings query in path_claim_register.
        apply_fixture_ddl(conn, """
            CREATE TABLE path_claims (
                id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'exclusive',
                integration_target TEXT NOT NULL,
                owner_kind TEXT,
                owner_item_id INTEGER
            );
            CREATE TABLE path_claim_targets (
                claim_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                declared_at TEXT
            );
            CREATE TABLE path_targets (
                id INTEGER PRIMARY KEY,
                path_string TEXT NOT NULL,
                kind TEXT DEFAULT 'file',
                parent_target_id INTEGER,
                materialization_state TEXT DEFAULT 'observed'
            );
            CREATE TABLE item_dependencies (
                id INTEGER PRIMARY KEY,
                dependent_item_id INTEGER,
                blocking_item_id INTEGER,
                gate_point TEXT,
                source TEXT
            );
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL,
                public_item_prefix TEXT NOT NULL
            );
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                project_sequence INTEGER
            );
        """)
        # The denial names the item by its public ref, so the identity the
        # renderer reads has to exist here; its sequence is deliberately its
        # own, not the internal id repeated back.
        conn.execute(
            "INSERT INTO projects (id, slug, public_item_prefix) "
            "VALUES (%s, %s, %s)",
            (PROJECT_ID, "yoke", ITEM_PREFIX),
        )
        conn.execute(
            "INSERT" + " INTO items (id, project_id, project_sequence) "
            "VALUES (%s, %s, %s)",
            (OVERLAP_INTERNAL_ID, PROJECT_ID, OVERLAP_SEQUENCE),
        )
        conn.execute("INSERT INTO path_targets VALUES (10, 'a.py', 'file', NULL, 'observed')")
        conn.execute("INSERT INTO path_targets VALUES (11, 'b.py', 'file', NULL, 'observed')")
        # Conflicting active claim covering both targets.
        conn.execute(
            "INSERT INTO path_claims "
            "(id, state, mode, integration_target, owner_kind, owner_item_id) "
            "VALUES (%s, %s, %s, %s, 'item', %s)",
            (200, "active", "exclusive", "main", 999),
        )
        conn.execute(
            "INSERT INTO path_claim_targets VALUES (%s, %s, %s)",
            (200, 10, None),
        )
        conn.execute(
            "INSERT INTO path_claim_targets VALUES (%s, %s, %s)",
            (200, 11, None),
        )
        conn.commit()

        # Pin the overlap classifier to INCOMPATIBLE so the conflict
        # surfaces (real classifier wants more schema).
        import yoke_core.domain.path_claims_read as read_mod

        original = read_mod.classify_overlap

        def _stub(*args, **kwargs):
            return OverlapClassification.INCOMPATIBLE

        read_mod.classify_overlap = _stub
        try:
            body = compose_overlap_denial(
                item_id=OVERLAP_INTERNAL_ID,
                integration_target="main",
                candidate_target_ids=[10, 11],
                base_message="overlap on main",
                conn=conn,
            )
        finally:
            read_mod.classify_overlap = original
            conn.close()

        assert f"{ITEM_PREFIX}-{OVERLAP_SEQUENCE}" in body
        assert str(OVERLAP_INTERNAL_ID) not in body
        assert "claim 200" in body
        assert "a.py" in body and "b.py" in body
        # Resolution command points at the first conflicting claim.
        assert "--conflicting-claim 200" in body
        # Overlapping paths threaded through into --paths arg.
        assert "--paths a.py,b.py" in body
