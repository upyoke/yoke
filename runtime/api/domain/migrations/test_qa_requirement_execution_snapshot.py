"""Governed migration coverage for immutable QA execution snapshots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime.api.domain.migrations import (
    qa_requirement_execution_snapshot as source_wrapper,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.migrations.qa_requirement_execution_snapshot import (
    MIGRATION_NAME,
    SNAPSHOT_COLUMNS,
    apply,
    invariants,
)
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_deployment_run,
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.schema_common import _column_exists


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("qa_requirement_execution_snapshot.migration.json")


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    from yoke_core.domain.migration_apply_manifest import (
        validate_manifest_payload,
    )

    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.SNAPSHOT_COLUMNS == SNAPSHOT_COLUMNS
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def _seed_requirements(conn) -> tuple[int, int]:
    insert_item(conn, id=42, title="Snapshot QA", workflow_id="issue")
    plan = create_plan(
        conn,
        project="yoke",
        slug="snapshot-plan",
        name="Snapshot plan",
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the command.",
                "expected_outcome": "The command passes.",
                "method_config": {"command": "true"},
                "host_baselines": ["first", "second"],
            }
        ],
    )
    set_project_default(
        conn,
        plan_id=plan["id"],
        workflow_id="issue",
        transition_id="implemented",
    )
    materialized = materialize_for_item(
        conn,
        item_id=42,
        transition_id="implemented",
    )
    ad_hoc = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id, qa_kind, qa_phase, blocking_mode, requirement_source, "
        "method_id, instructions, expected_outcome, method_config, created_at"
        ") VALUES (42, 'method_case', 'verification', 'blocking', "
        "'explicit', 'browser-inspection', 'Inspect.', 'Looks correct.', "
        "%s, '2026-07-27T00:00:00Z') RETURNING id",
        (json.dumps({"steps": [{"action": "navigate", "route": "/"}]}),),
    ).fetchone()
    conn.commit()
    return int(materialized["created_requirement_ids"][0]), int(ad_hoc[0])


def test_apply_backfills_plan_and_ad_hoc_rows_then_reapplies_cleanly(test_db) -> None:
    plan_requirement, ad_hoc_requirement = _seed_requirements(test_db)
    test_db.execute(
        "UPDATE qa_methods SET updated_at='snapshot-method-sentinel' WHERE id='command'"
    )
    for column in SNAPSHOT_COLUMNS:
        test_db.execute(f"ALTER TABLE qa_requirements DROP COLUMN IF EXISTS {column}")
    test_db.execute("ALTER TABLE qa_runs DROP COLUMN IF EXISTS capture_degraded_reason")
    test_db.commit()
    assert not _column_exists(test_db, "qa_requirements", "executor_id")
    assert not _column_exists(test_db, "qa_runs", "capture_degraded_reason")
    method_state = [
        tuple(row)
        for row in test_db.execute(
            "SELECT id, updated_at FROM qa_methods ORDER BY id"
        ).fetchall()
    ]

    apply(test_db)
    invariants(test_db)

    plan_rows = test_db.execute(
        "SELECT case_position, baseline_position, method_name, executor_id, "
        "required_capability_kind, verdict_path "
        "FROM qa_requirements WHERE plan_id IS NOT NULL ORDER BY id"
    ).fetchall()
    ad_hoc = test_db.execute(
        "SELECT case_position, baseline_position, method_name, executor_id, "
        "verdict_path FROM qa_requirements WHERE id=%s",
        (ad_hoc_requirement,),
    ).fetchone()
    first_state = [tuple(row) for row in plan_rows]

    assert first_state == [
        (1, 1, "Command", "worktree_run", None, "automatic"),
        (1, 2, "Command", "worktree_run", None, "automatic"),
    ]
    assert tuple(ad_hoc) == (
        None,
        None,
        "Browser inspection",
        "browser_substrate",
        "agent",
    )
    assert plan_requirement > 0
    assert not _column_exists(test_db, "qa_runs", "capture_degraded_reason")
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT id, updated_at FROM qa_methods ORDER BY id"
        ).fetchall()
    ] == method_state

    apply(test_db)
    invariants(test_db)
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT case_position, baseline_position, method_name, "
            "executor_id, required_capability_kind, verdict_path "
            "FROM qa_requirements WHERE plan_id IS NOT NULL ORDER BY id"
        ).fetchall()
    ] == first_state
    assert not _column_exists(test_db, "qa_runs", "capture_degraded_reason")
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT id, updated_at FROM qa_methods ORDER BY id"
        ).fetchall()
    ] == method_state


def test_invariants_scope_plan_positions_to_the_deployment_run(test_db) -> None:
    _seed_requirements(test_db)
    for run_id in ("run-20260729-901", "run-20260729-902"):
        test_db.execute(
            "INSERT INTO deployment_runs("
            "id, project_id, flow, status, created_at"
            ") SELECT %s, project_id, 'stage', 'created', "
            "'2026-07-29T00:00:00Z' FROM qa_plans "
            "WHERE slug='snapshot-plan'",
            (run_id,),
        )
        test_db.commit()
        materialize_for_deployment_run(
            test_db,
            deployment_run_id=run_id,
            plan="snapshot-plan",
            project="yoke",
        )

    apply(test_db)
    invariants(test_db)


def test_apply_leaves_transaction_control_with_the_caller(test_db) -> None:
    for column in SNAPSHOT_COLUMNS:
        test_db.execute(f"ALTER TABLE qa_requirements DROP COLUMN IF EXISTS {column}")
    test_db.commit()

    apply(test_db)
    assert all(
        _column_exists(test_db, "qa_requirements", column)
        for column in SNAPSHOT_COLUMNS
    )
    test_db.rollback()

    assert all(
        not _column_exists(test_db, "qa_requirements", column)
        for column in SNAPSHOT_COLUMNS
    )
