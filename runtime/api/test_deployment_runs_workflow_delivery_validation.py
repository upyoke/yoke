"""Workflow-aware deployment composition eligibility and diagnostics."""

from __future__ import annotations

from runtime.api.test_deployment_runs_full_helpers import db_path, _conn  # noqa: F401
from yoke_core.domain import deployment_runs as runs
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin


def _insert_item(
    database: str,
    *,
    item_id: int,
    workflow: str,
    status: str,
    project_id: int = 1,
    sequence: int | None = None,
) -> None:
    conn = _conn(database)
    try:
        workflow_id, version_id = resolve_current_workflow_pin(conn, workflow)
        conn.execute(
            "INSERT INTO items ("
            "id, title, workflow_id, workflow_version_id, status, project_id, "
            "project_sequence, created_at, updated_at"
            ") VALUES (%s, 'delivery member', %s, %s, %s, %s, %s, "
            "'2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z')",
            (
                item_id,
                workflow_id,
                version_id,
                status,
                project_id,
                sequence if sequence is not None else item_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_continuous_slice_implementation_is_delivery_ready(db_path):
    item_id = 701
    _insert_item(
        db_path,
        item_id=item_id,
        workflow="blitz",
        status="implementing",
    )
    run_id = runs.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    runs.cmd_add_item(run_id, item_id, db_path=db_path)

    assert runs.cmd_validate_composition(run_id, db_path=db_path) == (True, "OK")
    assert runs.cmd_check_batch_compatibility(
        "yoke", "yoke-internal", [item_id], db_path=db_path
    ) == (True, "OK")


def test_preimplementation_stage_is_not_delivery_ready(db_path):
    item_id = 702
    _insert_item(
        db_path,
        item_id=item_id,
        workflow="blitz",
        status="refined-idea",
    )

    ok, message = runs.cmd_check_batch_compatibility(
        "yoke", "yoke-internal", [item_id], db_path=db_path
    )
    assert not ok
    assert "YOK-702 (status=refined-idea)" in message


def test_external_project_diagnostic_uses_public_reference(db_path):
    item_id = 703
    conn = _conn(db_path)
    try:
        conn.execute(
            "UPDATE projects SET public_item_prefix = 'EXT' WHERE id = 2"
        )
        conn.commit()
    finally:
        conn.close()
    _insert_item(
        db_path,
        item_id=item_id,
        workflow="issue",
        status="implemented",
        project_id=2,
        sequence=5,
    )
    run_id = runs.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, '2026-08-01T00:00:00Z')",
            (run_id, item_id),
        )
        conn.commit()
    finally:
        conn.close()

    ok, message = runs.cmd_validate_composition(run_id, db_path=db_path)
    assert not ok
    assert "EXT-5 (project=externalwebapp)" in message
    assert "YOK-703" not in message
