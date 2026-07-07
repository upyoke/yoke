"""Tests for tentative path-claim registration plumbing.

Covers AC-2 (callers register tentative without broad parent claims)
and AC-10 (idea/readiness reference checks treat tentative registered
path targets as planned-equivalent implementation surfaces).
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401
    local_human,
)
from yoke_core.domain.idea_readiness_check_refs import is_module_or_planned_ref
from yoke_core.domain.path_claims_register import register_for_item
from yoke_core.domain.path_targets_states import (
    PLANNED,
    TENTATIVE,
)


class TestRegisterTentative:
    def test_register_for_item_threads_tentative_paths(self, conn):
        actor_id = local_human(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, project_id, project_sequence, "
            "created_at, updated_at) "
            "VALUES (501, 'Item 501', 'issue', 'idea', 1, 501, "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')"
        )
        claim_id = register_for_item(
            conn,
            item_id=501,
            integration_target="main",
            paths=[
                "runtime/api/domain/sure_thing.py",
                "runtime/api/domain/maybe_touched.py",
            ],
            actor_id=actor_id,
            tentative_paths=["runtime/api/domain/maybe_touched.py"],
            allow_planned=True,
        )
        rows = conn.execute(
            "SELECT pt.path_string, pt.materialization_state "
            "FROM path_claim_targets pct "
            "JOIN path_targets pt ON pt.id = pct.target_id "
            "WHERE pct.claim_id = %s "
            "ORDER BY pt.path_string",
            (claim_id,),
        ).fetchall()
        states = {str(r[0]): str(r[1]) for r in rows}
        assert states["runtime/api/domain/maybe_touched.py"] == TENTATIVE
        assert states["runtime/api/domain/sure_thing.py"] == PLANNED


class TestReadinessRefs:
    """AC-10 — readiness suppresses dotted refs for tentative targets too."""

    def test_tentative_target_suppresses_unresolved_function_ref(self, conn):
        """A dotted ref to a tentative-registered module file is suppressed.

        Mirrors the planned case: when the operator declared
        a tentative path-claim target for ``foo/bar.py`` and the spec
        body mentions ``foo.bar``, the readiness checker treats the
        reference as a known forward path rather than an unresolved
        function. The path uses a deliberately non-existent module
        directory so the on-disk check (carve-out 1) does not fire and
        the assertion exercises the tentative-aware DB query.
        """
        actor_id = local_human(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, project_id, project_sequence, "
            "created_at, updated_at) "
            "VALUES (502, 'Item 502', 'issue', 'idea', 1, 502, "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')"
        )
        register_for_item(
            conn,
            item_id=502,
            integration_target="main",
            paths=["runtime/__nonexistent__/forward_ref_module.py"],
            actor_id=actor_id,
            tentative_paths=["runtime/__nonexistent__/forward_ref_module.py"],
            allow_planned=True,
        )
        assert is_module_or_planned_ref(
            "runtime.__nonexistent__.forward_ref_module",
            item_id=502,
            conn=conn,
        ) is True
