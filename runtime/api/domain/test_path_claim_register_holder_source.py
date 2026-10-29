"""Overlap denials name the held item's bound skill as the dependency source.

A live work-claim holder records the coordination decision with the skill its
item's status is bound to; no holder pre-fills ``refine``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claim_register import compose_overlap_denial

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

    @pytest.mark.parametrize(
        ("workflow", "status", "source"),
        [
            ("dash", "idea", None),
            ("issue", "idea", None),
            ("dash", "implementing", "dash"),
            ("issue", "implementing", "implement"),
            ("issue", "polishing-implementation", "polish"),
            ("issue", "release", "usher"),
            ("blitz", "implementing", "blitz"),
            ("issue", "done", "<source>"),
        ],
    )
    def test_enumerates_conflicts_and_paths(
        self, tmp_path, workflow, status, source
    ) -> None:
        """A held item's source is the skill its status is bound to.

        ``source`` None means no session holds the item's work claim.
        """
        import json

        from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

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
        apply_fixture_ddl(
            conn,
            """
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
                declared_at TIMESTAMPTZ
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
                project_sequence INTEGER,
                workflow_id TEXT,
                workflow_version_id INTEGER,
                status TEXT
            );
            CREATE TABLE workflow_versions (
                id INTEGER PRIMARY KEY,
                workflow_id TEXT,
                version INTEGER,
                definition_json TEXT,
                definition_digest TEXT
            );
            CREATE TABLE harness_sessions (
                session_id TEXT PRIMARY KEY,
                mode TEXT
            );
            CREATE TABLE work_claims (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                target_kind TEXT NOT NULL,
                scope TEXT NOT NULL,
                claim_type TEXT NOT NULL DEFAULT 'exclusive',
                claimed_at TIMESTAMPTZ NOT NULL,
                released_at TIMESTAMPTZ
            );
        """,
        )
        # The denial names the item by its public ref, so the identity the
        # renderer reads has to exist here; its sequence is deliberately its
        # own, not the internal id repeated back.
        conn.execute(
            "INSERT INTO projects (id, slug, public_item_prefix) VALUES (%s, %s, %s)",
            (PROJECT_ID, "yoke", ITEM_PREFIX),
        )
        runtime = builtin_workflow_runtime(workflow)
        conn.execute(
            "INSERT INTO workflow_versions VALUES (%s, %s, %s, %s, %s)",
            (
                1,
                workflow,
                runtime.version,
                json.dumps(runtime.definition),
                runtime.definition_digest,
            ),
        )
        conn.execute(
            "INSERT" + " INTO items (id, project_id, project_sequence, workflow_id, "
            "workflow_version_id, status) VALUES (%s, %s, %s, %s, 1, %s)",
            (OVERLAP_INTERNAL_ID, PROJECT_ID, OVERLAP_SEQUENCE, workflow, status),
        )
        conn.execute(
            "INSERT" + " INTO items (id, project_id, project_sequence) "
            "VALUES (%s, %s, %s)",
            (999, PROJECT_ID, OVERLAP_SEQUENCE + 1),
        )
        conn.execute(
            "INSERT INTO path_targets VALUES (10, 'a.py', 'file', NULL, 'observed')"
        )
        conn.execute(
            "INSERT INTO path_targets VALUES (11, 'b.py', 'file', NULL, 'observed')"
        )
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
        if source is not None:
            conn.execute(
                "INSERT INTO harness_sessions (session_id, mode) VALUES (%s, %s)",
                ("sess-holder", "wait"),
            )
            conn.execute(
                "INSERT INTO work_claims "
                "(id, session_id, target_kind, scope, claim_type, claimed_at) "
                "VALUES (%s, %s, 'item', %s, 'exclusive', %s)",
                (
                    1,
                    "sess-holder",
                    '{"item_id": %d}' % OVERLAP_INTERNAL_ID,
                    "2026-10-16T00:00:00Z",
                ),
            )
        conn.commit()

        # Pin the overlap classifier to INCOMPATIBLE so the conflict
        # surfaces (real classifier wants more schema).
        import yoke_core.domain.path_claims_read as read_mod

        original = read_mod.classify_overlap

        def _stub(*args, **kwargs):
            return OverlapClassification.INCOMPATIBLE

        read_mod.classify_overlap = _stub
        from yoke_core.domain.path_claim_coordination_decision import (
            _suggested_commands,
        )

        try:
            body = compose_overlap_denial(
                item_id=OVERLAP_INTERNAL_ID,
                integration_target="main",
                candidate_target_ids=[10, 11],
                base_message="overlap on main",
                conn=conn,
            )
            coord = next(
                c
                for c in _suggested_commands(
                    conn, OVERLAP_INTERNAL_ID, 999, ["a.py"], 200
                )
                if "--gate-point coordination_only" in c
            )
        finally:
            read_mod.classify_overlap = original
            conn.close()

        assert f"{ITEM_PREFIX}-{OVERLAP_SEQUENCE}" in body
        assert str(OVERLAP_INTERNAL_ID) not in body
        assert "claim 200" in body
        assert "a.py" in body and "b.py" in body
        assert f"holder {ITEM_PREFIX}-{OVERLAP_SEQUENCE + 1}" in body
        if source is None:
            assert f"/yoke refine {ITEM_PREFIX}-{OVERLAP_SEQUENCE}" in body
            assert "coordination-decision-build" not in body
            assert " refine " in coord
        elif source == "<source>":
            assert "/yoke refine" not in body
            assert f"Item stage {status!r}" in body
            assert "yoke say --steering" in body
            assert "<source>" in coord
        else:
            assert "/yoke refine" not in body
            assert "coordination_only" in body
            assert f"source {source}" in body
            assert f"Continue /yoke {source} " in body
            assert "holder's landing" in body
            assert "yoke say --steering" in body
            assert f" {source} " in coord
