"""Tests for tentative path_targets coverage.

Covers AC-1, AC-2, AC-3, AC-4, AC-11 schema admits the
new ``tentative`` state, callers can register tentative coverage
without broad parent-directory claims, tentative targets participate
in overlap detection, and tentative targets promote to ``observed``
when later seen in a snapshot. The module-only constants check
asserts the DDL CHECK constraint matches the canonical state list.
"""

from __future__ import annotations

from typing import Any

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain._path_claims_test_helpers import conn  # noqa: F401
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from yoke_core.domain.path_claims_resolve import (
    resolve_or_plan_paths_to_target_ids,
)
from yoke_core.domain.path_registry import KIND_FILE
from yoke_core.domain.path_targets_materialization import (
    abandon_planned_target,
    find_planned_match,
    materialize_planned_target,
    plan_path_target,
    plan_tentative_path_target,
)
from yoke_core.domain.path_targets_states import (
    ABANDONED,
    ALL_STATES,
    OBSERVED,
    PLANNED,
    PRE_OBSERVATION_STATES,
    TENTATIVE,
)
from yoke_core.domain.schema_common import _get_check_constraint_defs


def _state_of(c: Any, target_id: int) -> str:
    row = c.execute(
        "SELECT materialization_state FROM path_targets WHERE id = %s",
        (target_id,),
    ).fetchone()
    return "" if row is None else str(row[0])


class TestStateConstants:
    """AC-11 — the constant owner mirrors the DDL CHECK domain."""

    def test_all_states_includes_tentative(self):
        assert TENTATIVE in ALL_STATES
        assert set(ALL_STATES) == {PLANNED, OBSERVED, ABANDONED, TENTATIVE}

    def test_pre_observation_states_includes_planned_and_tentative(self):
        assert set(PRE_OBSERVATION_STATES) == {PLANNED, TENTATIVE}

    def test_ddl_check_constraint_matches_constants(self, conn):
        definitions = _get_check_constraint_defs(conn, "path_targets")
        assert definitions, "path_targets DDL missing from fixture"
        sql = "\n".join(definitions)
        for state in ALL_STATES:
            assert f"'{state}'" in sql, (
                f"DDL CHECK domain missing {state!r} — constants module "
                "and DDL drifted out of sync"
            )


class TestSchemaAdmitsTentative:
    """AC-1 — the CHECK domain admits the new ``tentative`` literal."""

    def test_direct_insert_with_tentative_succeeds(self, conn):
        row = conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at, "
            " materialization_state, materialization_updated_at) "
            "VALUES (1, 'file', 'tentative_direct.py', 1, "
            "'2026-05-01T00:00:00Z', 'tentative', "
            "'2026-05-01T00:00:00Z') RETURNING id"
        ).fetchone()
        assert _state_of(conn, int(row[0])) == TENTATIVE

    def test_direct_insert_with_unknown_state_rejects(self, conn):
        with pytest.raises(db_backend.integrity_error_types(conn)):
            conn.execute(
                "INSERT INTO path_targets "
                "(project_id, kind, path_string, generation, created_at, "
                " materialization_state, materialization_updated_at) "
                "VALUES (1, 'file', 'bogus.py', 1, "
                "'2026-05-01T00:00:00Z', 'speculative', "
                "'2026-05-01T00:00:00Z')"
            )


class TestPlanTentative:
    """AC-2 — callers can register tentative paths without broad parents."""

    def test_plan_mints_tentative_row(self, conn):
        target_id = plan_tentative_path_target(
            conn, project_id=1,
            path_string="future_predicted.py", kind=KIND_FILE,
            item_id=101,
        )
        assert _state_of(conn, target_id) == TENTATIVE

    def test_existing_observed_is_reused_not_downgraded(self, conn):
        row = conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at, "
            " materialization_state, materialization_updated_at) "
            "VALUES (1, 'file', 'already_here.py', 1, "
            "'2026-05-01T00:00:00Z', 'observed', "
            "'2026-05-01T00:00:00Z') RETURNING id"
        ).fetchone()
        observed_id = int(row[0])
        result = plan_tentative_path_target(
            conn, project_id=1,
            path_string="already_here.py", kind=KIND_FILE,
            item_id=102,
        )
        assert result == observed_id
        assert _state_of(conn, observed_id) == OBSERVED

    def test_existing_planned_is_not_downgraded_to_tentative(self, conn):
        planned_id = plan_path_target(
            conn, project_id=1,
            path_string="committed_path.py", kind=KIND_FILE,
            item_id=103,
        )
        result = plan_tentative_path_target(
            conn, project_id=1,
            path_string="committed_path.py", kind=KIND_FILE,
            item_id=104,
        )
        assert result == planned_id
        assert _state_of(conn, planned_id) == PLANNED

    def test_tentative_is_sticky_against_replanning_as_planned(self, conn):
        """``plan_path_target`` on existing tentative leaves the state alone.

        Auto-coordination paths (the dependency resolver, the
        upstream-claim resolver) call ``plan_path_target`` again
        during ``register_for_item`` for the same path list. Letting
        ``plan_path_target`` flip tentative → planned would overwrite
        the operator's deliberate-tentative intent on every register
        round-trip. Tentative coverage upgrades only via explicit
        amend / re-register-without-tentative_paths.
        """
        tentative_id = plan_tentative_path_target(
            conn, project_id=1,
            path_string="sticky_tentative.py", kind=KIND_FILE,
            item_id=105,
        )
        replanned_id = plan_path_target(
            conn, project_id=1,
            path_string="sticky_tentative.py", kind=KIND_FILE,
            item_id=105,
        )
        assert replanned_id == tentative_id
        assert _state_of(conn, tentative_id) == TENTATIVE

    def test_resolve_or_plan_with_tentative_paths_kwarg(self, conn):
        target_ids = resolve_or_plan_paths_to_target_ids(
            conn, 1,
            ["definite.py", "maybe.py"],
            item_id=106,
            tentative_paths=["maybe.py"],
        )
        assert len(target_ids) == 2
        states = {tid: _state_of(conn, tid) for tid in target_ids}
        assert PLANNED in states.values()
        assert TENTATIVE in states.values()


class TestOverlapDetection:
    """AC-3 — tentative targets participate in overlap/conflict detection."""

    def test_tentative_target_overlap_blocks_second_claim(self, conn):
        from yoke_core.domain._path_claims_test_helpers import local_human

        actor = local_human(conn)
        tentative_id = plan_tentative_path_target(
            conn, project_id=1,
            path_string="contested.py", kind=KIND_FILE,
            item_id=201,
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[tentative_id], item_id=201,
        )
        classification = classify_overlap(
            conn,
            target_ids=[tentative_id],
            integration_target="main",
            phase="register",
        )
        assert classification is OverlapClassification.INCOMPATIBLE


class TestMaterialization:
    """AC-4 — tentative targets promote to observed when seen."""

    def test_find_planned_match_returns_tentative_row(self, conn):
        target_id = plan_tentative_path_target(
            conn, project_id=1,
            path_string="future_observed.py", kind=KIND_FILE,
            item_id=301,
        )
        match = find_planned_match(
            conn, project_id=1,
            path_string="future_observed.py", kind=KIND_FILE,
            parent_target_id=conn.execute(
                "SELECT parent_target_id FROM path_targets WHERE id = %s",
                (target_id,),
            ).fetchone()[0],
        )
        assert match == target_id

    def test_materialize_promotes_tentative_to_observed(self, conn):
        target_id = plan_tentative_path_target(
            conn, project_id=1,
            path_string="will_be_observed.py", kind=KIND_FILE,
            item_id=302,
        )
        flipped = materialize_planned_target(
            conn, target_id=target_id, commit_sha="abc123",
        )
        assert flipped is True
        assert _state_of(conn, target_id) == OBSERVED

    def test_abandon_tentative_target_succeeds(self, conn):
        target_id = plan_tentative_path_target(
            conn, project_id=1,
            path_string="will_be_abandoned.py", kind=KIND_FILE,
            item_id=303,
        )
        flipped = abandon_planned_target(
            conn, target_id=target_id, reason="tentative-untouched-on-cancel",
        )
        assert flipped is True
        assert _state_of(conn, target_id) == ABANDONED
