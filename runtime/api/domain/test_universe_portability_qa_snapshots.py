"""Portable-universe coverage for immutable QA requirement snapshots."""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.domain.test_universe_portability import _canonical_test_universe
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import universe_portability as portability
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_snapshot_convergence import SNAPSHOT_COLUMNS
from yoke_core.domain.schema_fingerprint import (
    fingerprint_portable_postgres_schema,
)


def _create_requirement_source(
    conn,
    *,
    item_id: int,
    slug: str,
    host_baselines: list[str],
) -> tuple[int, int]:
    insert_item(
        conn,
        id=item_id,
        title="Portable requirement snapshot",
        workflow_id="issue",
    )
    plan = create_plan(
        conn,
        project="yoke",
        slug=slug,
        name="Portable requirement snapshot",
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "portable-command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the portable command.",
                "expected_outcome": "The portable command passes.",
                "method_config": {"command": "true"},
                "host_baselines": host_baselines,
            }
        ],
    )
    return int(plan["id"]), item_id


def test_restore_backfills_requirement_snapshots_from_an_older_archive(tmp_path):
    with _canonical_test_universe() as (source, source_dsn):
        with _canonical_test_universe() as (reference, _reference_dsn):
            expected_fingerprint = fingerprint_portable_postgres_schema(reference)

        plan_id, item_id = _create_requirement_source(
            source,
            item_id=88106,
            slug="portable-requirement-snapshot",
            host_baselines=["legacy-host"],
        )
        requirement_id = int(
            source.execute(
                "INSERT INTO qa_requirements("
                "item_id, qa_kind, qa_phase, blocking_mode, "
                "requirement_source, plan_id, plan_case_key, method_id, "
                "host_baseline, workflow_transition_id, instructions, "
                "expected_outcome, method_config, created_at"
                ") VALUES (%s, 'plan_case', 'verification', 'blocking', "
                "'flow_derived', %s, 'portable-command', 'command', "
                "'legacy-host', 'implemented', 'Run the portable command.', "
                "'The portable command passes.', '{\"command\":\"true\"}', "
                "'then') RETURNING id",
                (item_id, plan_id),
            ).fetchone()[0]
        )
        for column in SNAPSHOT_COLUMNS:
            source.execute(
                f"ALTER TABLE qa_requirements DROP COLUMN IF EXISTS {column}"
            )
        source.commit()

        archive = tmp_path / "older-requirement-snapshot.dump"
        portability.dump_universe(source_dsn, archive)
        target_name = pg_testdb.create_test_database()
        target_dsn = pg_testdb.dsn_for_test_database(target_name)
        try:
            portability.restore_universe(archive, target_dsn)
            portability.converge_and_validate_restored_universe(
                target_dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected_fingerprint,
            )
            with psycopg.connect(target_dsn) as target:
                assert target.execute(
                    "SELECT case_position, baseline_position, method_name, "
                    "runner_id, required_capability_kind, verdict_path "
                    "FROM qa_requirements WHERE id = %s",
                    (requirement_id,),
                ).fetchone() == (
                    1,
                    1,
                    "Command",
                    "worktree_run",
                    None,
                    "automatic",
                )
        finally:
            pg_testdb.drop_test_database(target_name)


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
            "'{\"command\":\"true\"}', 'then')",
            (item_id, plan_id),
        )
        conn.commit()
        expected_fingerprint = fingerprint_portable_postgres_schema(conn)

        with pytest.raises(
            portability.ArchiveCompatibilityError,
            match="QA requirement snapshots",
        ):
            portability.converge_and_validate_restored_universe(
                dsn,
                expected_org_slug="default",
                expected_schema_fingerprint=expected_fingerprint,
            )
