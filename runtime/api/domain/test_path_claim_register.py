"""Unit tests for :mod:`yoke_core.domain.path_claim_register`.

The overlap-denial body embeds the conflicting claim
id(s), the overlapping path strings, and the
``yoke claims path coordination-decision-build`` command shape so the operator's
next move is one paste.
"""

from __future__ import annotations

from yoke_core.domain.path_claim_register import compose_overlap_denial


class TestComposeOverlapDenialNoConflicts:
    """When the conflict scan finds no rows (e.g. conn=None under unit
    tests), the body still names the item + integration target and emits
    the resolution-command template with placeholders so the contract
    shape is visible."""

    def test_includes_header_and_resolution_command(self) -> None:
        body = compose_overlap_denial(
            item_id=123,
            integration_target="main",
            candidate_target_ids=[],
            base_message="overlap reason text",
            conn=None,
        )
        assert "BLOCKED: path-claim register overlap" in body
        assert "YOK-123" in body
        assert "integration_target='main'" in body
        assert "overlap reason text" in body
        assert "yoke claims path coordination-decision-build" in body
        assert "--item YOK-123" in body

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
                item_id INTEGER
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
                dependent_item INTEGER,
                blocking_item INTEGER,
                gate_point TEXT,
                source TEXT
            );
        """)
        conn.execute("INSERT INTO path_targets VALUES (10, 'a.py', 'file', NULL, 'observed')")
        conn.execute("INSERT INTO path_targets VALUES (11, 'b.py', 'file', NULL, 'observed')")
        # Conflicting active claim covering both targets.
        conn.execute(
            "INSERT INTO path_claims VALUES (%s, %s, %s, %s, %s)",
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
                item_id=42,
                integration_target="main",
                candidate_target_ids=[10, 11],
                base_message="overlap on main",
                conn=conn,
            )
        finally:
            read_mod.classify_overlap = original
            conn.close()

        assert "YOK-42" in body
        assert "claim 200" in body
        assert "a.py" in body and "b.py" in body
        # Resolution command points at the first conflicting claim.
        assert "--conflicting-claim 200" in body
        # Overlapping paths threaded through into --paths arg.
        assert "--paths a.py,b.py" in body
