"""Whole-definition flow writes, immutable history, and runtime guards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import deployment_runs_schema, schema
from yoke_core.domain.deployment_flow_versioning import (
    cmd_reorder_stages,
    cmd_update_definition,
    cmd_validate_definition,
    cmd_version_definition,
)
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.flow_crud import cmd_delete, cmd_set_status
from yoke_core.domain.schema_init import converge_core_schema
from yoke_core.domain.project_seed_test_helpers import (
    SEED_PROJECT_IDS,
    seed_project_identities,
)


LEGACY_STAGES = json.dumps(
    [
        {"name": "deploy", "step_runner": "auto"},
        {"name": "complete", "step_runner": "auto"},
    ]
)
ADVANCED_STAGES = json.dumps(
    [
        {
            "name": "preview",
            "step_runner": "ephemeral-deploy",
            "stage_kind": "execution",
            "scope": "run",
            "target": {"kind": "run_preview", "capability": "ephemeral-env"},
        },
        {
            "name": "preview-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "run",
            "target": {"kind": "run_preview", "source_stage": "preview"},
            "verdict": {"mode": "agent_only"},
        },
    ]
)


def _create_legacy(conn: Any, flow_id: str = "mutable-flow") -> None:
    cmd_create(conn, flow_id, "yoke", "Mutable flow", "", LEGACY_STAGES)


def _seed_ephemeral_capability(
    conn: Any, project_id: int = SEED_PROJECT_IDS["yoke"]
) -> None:
    """Register the ``ephemeral-env`` capability an ADVANCED_STAGES preview
    stage names, so ``validate_stage_references`` resolves it like any other
    real project instead of refusing on a fixture gap."""
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, 'ephemeral-env', %s, %s) "
        "ON CONFLICT DO NOTHING",
        (
            project_id,
            '{"trigger":"github-push","preview_domain":"preview.example.com"}',
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()


def test_run_preview_target_requires_registered_capability(test_db: Any) -> None:
    # No ephemeral-env capability seeded for the "yoke" test project: a
    # run_preview stage naming it must refuse the same way an unregistered
    # persistent_environment target does, not silently validate.
    with pytest.raises(
        LookupError, match="capability 'ephemeral-env' is not registered"
    ) as excinfo:
        cmd_validate_definition(
            test_db, project="yoke", stages=ADVANCED_STAGES, status="disabled"
        )
    # The refusal teaches the fix, not just the reason: an operator reading it
    # must not have to go hunting for how to register the capability.
    assert "capability-settings merge" in str(excinfo.value)
    assert "--cap-type ephemeral-env" in str(excinfo.value)


def test_advanced_definition_validates_but_cannot_activate_yet(test_db: Any) -> None:
    _seed_ephemeral_capability(test_db)
    result = cmd_validate_definition(
        test_db, project="yoke", stages=ADVANCED_STAGES, status="disabled"
    )
    assert result == {
        "valid": True,
        "definition_schema_version": 2,
        "execution_supported": False,
        "serving_schema_version": 1,
    }
    with pytest.raises(ValueError, match="keep the definition disabled"):
        cmd_validate_definition(
            test_db, project="yoke", stages=ADVANCED_STAGES, status="active"
        )


def test_complete_update_and_reorder_preserve_one_flow_identity(test_db: Any) -> None:
    _create_legacy(test_db)
    updated = cmd_update_definition(
        test_db,
        "mutable-flow",
        {"description": "Ordered release", "on_failure": "continue"},
    )
    assert updated["description"] == "Ordered release"
    assert updated["on_failure"] == "continue"
    reordered = cmd_reorder_stages(test_db, "mutable-flow", ["complete", "deploy"])
    assert [stage["name"] for stage in json.loads(reordered["stages"])] == [
        "complete",
        "deploy",
    ]


def test_used_definition_is_immutable_but_can_publish_a_new_version(
    test_db: Any,
) -> None:
    _create_legacy(test_db, "used-flow")
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES ('run-used-flow',1,'used-flow','cancelled','2026-09-14T00:00:00Z')"
    )
    test_db.commit()
    with pytest.raises(ValueError, match="historical run"):
        cmd_update_definition(test_db, "used-flow", {"description": "changed"})
    with pytest.raises(ValueError, match="historical run"):
        cmd_delete(test_db, "used-flow")

    published = cmd_version_definition(
        test_db,
        "used-flow",
        "used-flow-v2",
        name="Used flow v2",
        changes={"description": "New immutable definition"},
    )
    assert published["status"] == "disabled"
    assert published["supersedes_flow_id"] == "used-flow"


def test_advanced_definition_is_authored_disabled_and_status_guarded(
    test_db: Any,
) -> None:
    _seed_ephemeral_capability(test_db)
    cmd_create(
        test_db,
        "preview-flow",
        "yoke",
        "Preview flow",
        "",
        ADVANCED_STAGES,
        status="disabled",
    )
    row = test_db.execute(
        "SELECT definition_schema_version,status FROM deployment_flows "
        "WHERE id='preview-flow'"
    ).fetchone()
    assert (row["definition_schema_version"], row["status"]) == (2, "disabled")
    with pytest.raises(ValueError, match="keep the definition disabled"):
        cmd_set_status(test_db, "preview-flow", "active")


def test_flow_plan_selection_is_project_scoped(test_db: Any) -> None:
    _seed_ephemeral_capability(test_db)
    test_db.execute(
        "INSERT INTO qa_plans(id,project_id,slug,name,description,created_at,updated_at) "
        "VALUES (91,2,'foreign-plan','Foreign plan','',%s,%s)",
        ("2026-09-14T00:00:00Z", "2026-09-14T00:00:00Z"),
    )
    test_db.execute(
        "INSERT INTO qa_plan_cases(id,plan_id,case_key,position,method_id,"
        "instructions,expected_outcome,created_at,updated_at) VALUES "
        "(92,91,'smoke',1,'command','run smoke','passes',%s,%s)",
        ("2026-09-14T00:00:00Z", "2026-09-14T00:00:00Z"),
    )
    test_db.commit()
    stages = json.loads(ADVANCED_STAGES)
    stages[1]["cases"] = {"plan_id": 91}
    with pytest.raises(ValueError, match="belongs to another project"):
        cmd_validate_definition(
            test_db,
            project="yoke",
            stages=json.dumps(stages),
            status="disabled",
        )


def _flow_lineage_reference(conn: Any) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT ccu.table_name,ccu.column_name "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name=kcu.constraint_name "
        "AND tc.constraint_schema=kcu.constraint_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "ON tc.constraint_name=ccu.constraint_name "
        "AND tc.constraint_schema=ccu.constraint_schema "
        "WHERE tc.constraint_type='FOREIGN KEY' "
        "AND tc.table_name='deployment_flows' "
        "AND kcu.column_name='supersedes_flow_id'"
    ).fetchone()
    return tuple(row) if row is not None else None


def _complete_schema() -> None:
    schema.cmd_init()
    deployment_runs_schema.cmd_init()


def test_flow_lineage_reference_matches_fresh_schema_after_boot_convergence(
    tmp_path: Path,
) -> None:
    with init_test_db(tmp_path, apply_schema=_complete_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            expected = _flow_lineage_reference(conn)
            assert expected == ("deployment_flows", "id")
            conn.execute("ALTER TABLE deployment_flows DROP COLUMN supersedes_flow_id")
            conn.commit()
            converge_core_schema(conn)
            assert _flow_lineage_reference(conn) == expected
        finally:
            conn.close()


@pytest.mark.parametrize("initializer", ["flow", "deployment_runs"])
def test_delivery_intent_constraint_matches_both_initialization_orders(
    tmp_path: Path,
    initializer: str,
) -> None:
    with init_test_db(tmp_path / initializer, apply_schema=_complete_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            seed_project_identities(conn)
            _create_legacy(conn, "intent-flow")
            conn.execute(
                "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
                "VALUES (%s,1,'intent-flow','created',%s)",
                (f"run-{initializer}", "2026-09-14T00:00:00Z"),
            )
            conn.execute("ALTER TABLE deployment_run_items DROP COLUMN delivery_intent")
            conn.commit()
            if initializer == "flow":
                converge_core_schema(conn)
                converge_core_schema(conn)
            else:
                conn.close()
                deployment_runs_schema.cmd_init(db_path)
                deployment_runs_schema.cmd_init(db_path)
                conn = connect_test_db(db_path)

            with pytest.raises(Exception) as exc_info:
                conn.execute(
                    "INSERT INTO deployment_run_items"
                    "(run_id,item_id,added_at,delivery_intent) "
                    "VALUES (%s,91,%s,'invalid')",
                    (f"run-{initializer}", "2026-09-14T00:00:00Z"),
                )
            assert "delivery_intent" in str(exc_info.value)
            conn.rollback()
        finally:
            conn.close()
