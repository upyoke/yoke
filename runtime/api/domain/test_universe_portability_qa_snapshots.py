"""Portable-universe coverage for immutable QA requirement snapshots."""

from __future__ import annotations

from runtime.api.domain.universe_portability_qa_snapshots_test_support import (
    _create_requirement_source as _create_requirement_source,
    assert_requirement_snapshot_restored as assert_requirement_snapshot_restored,
    seed_older_requirement_snapshot as seed_older_requirement_snapshot,
)


import pytest

from runtime.api.domain.universe_portability_test_support import (
    _canonical_test_universe,
)
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)


def test_restore_acceptance_rejects_invalid_requirement_snapshot() -> None:
    with _canonical_test_universe() as (conn, dsn):
        plan_id, item_id = _create_requirement_source(
            conn,
            item_id=88107,
            slug="invalid-portable-requirement-snapshot",
            host_baselines=[],
        )
        conn.execute(
            "INSERT INTO qa_requirements("
            "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
            "plan_id, plan_case_key, case_position, baseline_position, "
            "method_id, method_name, runner_id, verdict_path, "
            "workflow_transition_id, instructions, expected_outcome, "
            "method_config, created_at"
            ") VALUES (%s, 'plan_case', 'verification', 'blocking', "
            "'flow_derived', %s, 'portable-command', 0, 1, 'command', "
            "'Command', 'worktree_run', 'automatic', 'implemented', "
            "'Run the command.', 'The command passes.', "
            "'{\"command\":\"true\"}', '2026-10-01T00:00:00Z')",
            (item_id, plan_id),
        )
        conn.commit()
        expected_fingerprint = fingerprint_portable_postgres_schema(conn)
        # Release catalog/source-table locks before convergence on another connection.
        conn.commit()

        with pytest.raises(
            portability.ArchiveCompatibilityError,
            match="QA requirement snapshots",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected_fingerprint,
            )
