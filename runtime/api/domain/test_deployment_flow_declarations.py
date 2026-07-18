"""Generic project-owned deployment-flow declaration coverage."""

from __future__ import annotations

from copy import deepcopy
import pytest

from yoke_core.domain import json_helper
from yoke_core.domain.deployment_flow_declarations import (
    normalize_document,
    reconcile_project_flows,
)
from yoke_core.domain.flow_init import cmd_init as flow_cmd_init
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_structure import create_project_structure_tables
from runtime.api.fixtures.backlog import insert_deployment_run


def _seed_project(conn) -> None:
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        "VALUES (71, 'acme', 'Acme', 'ACM', '2026-01-01T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING"
    )
    conn.commit()
    flow_cmd_init(conn)
    create_project_structure_tables(conn)


def _document() -> dict:
    return {
        "schema": 1,
        "default_flow": "acme-production",
        "flows": [
            {
                "id": "acme-production",
                "name": "Production",
                "description": "Deploy the selected release",
                "stages": [
                    {"name": "merged", "executor": "auto"},
                    {"name": "deploy", "executor": "github-actions-workflow",
                     "workflow": "acme-deploy.yml"},
                    {"name": "complete", "executor": "auto"},
                ],
                "target_env": "production",
                "done_description": "Production deployment completed",
            },
            {
                "id": "acme-internal",
                "name": "Internal",
                "stages": [
                    {"name": "merged", "executor": "auto"},
                    {"name": "complete", "executor": "auto"},
                ],
            },
        ],
    }


def test_reconcile_is_additive_and_idempotent(test_db) -> None:
    _seed_project(test_db)

    first = reconcile_project_flows(test_db, "acme", _document())
    second = reconcile_project_flows(test_db, "acme", _document())

    assert first["created"] == ["acme-production", "acme-internal"]
    assert second["unchanged"] == ["acme-production", "acme-internal"]
    assert second["default_flow"] == "acme-production"
    assert first["default_flow_updated"] is True
    assert second["default_flow_updated"] is False
    row = test_db.execute(
        "SELECT payload FROM project_structure "
        "WHERE project_id=%s AND family='deploy_defaults'",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()
    assert json_helper.loads_text(str(row[0])) == {
        "deployment_flow": "acme-production",
    }


def test_omitted_historical_rows_are_never_pruned(test_db) -> None:
    _seed_project(test_db)
    reconcile_project_flows(test_db, "acme", _document())
    reduced = _document()
    reduced["flows"] = reduced["flows"][:1]

    reconcile_project_flows(test_db, "acme", reduced)

    assert test_db.execute(
        "SELECT status FROM deployment_flows WHERE id='acme-internal'"
    ).fetchone()[0] == "active"


def test_absent_retirements_do_not_create_legacy_rows(test_db) -> None:
    _seed_project(test_db)
    document = _document()
    document["retire_if_present"] = ["acme-legacy-release"]

    result = reconcile_project_flows(test_db, "acme", document)

    assert result["retired"] == []
    assert result["retire_absent"] == ["acme-legacy-release"]
    assert test_db.execute(
        "SELECT COUNT(*) FROM deployment_flows "
        "WHERE id='acme-legacy-release'"
    ).fetchone()[0] == 0


def test_live_retirement_disables_predecessors_and_preserves_runs(test_db) -> None:
    _seed_project(test_db)
    stages = json_helper.dumps_compact([
        {"name": "merged", "executor": "auto"},
        {"name": "complete", "executor": "auto"},
    ])
    test_db.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, status, created_at) "
        "VALUES ('acme-legacy-release', %s, 'Legacy Release', %s, "
        "'active', '2026-01-01T00:00:00Z')",
        (resolve_project_id(test_db, "acme"), stages),
    )
    test_db.commit()
    insert_deployment_run(
        test_db,
        id="run-legacy-release",
        project="acme",
        flow="acme-legacy-release",
        status="succeeded",
        current_stage="complete",
    )
    document = _document()
    document["retire_if_present"] = ["acme-legacy-release"]

    result = reconcile_project_flows(test_db, "acme", document)

    assert result["retired"] == ["acme-legacy-release"]
    assert test_db.execute(
        "SELECT status FROM deployment_flows "
        "WHERE id='acme-legacy-release'"
    ).fetchone()[0] == "disabled"
    assert test_db.execute(
        "SELECT flow FROM deployment_runs WHERE id='run-legacy-release'"
    ).fetchone()[0] == "acme-legacy-release"


def test_retirement_cannot_disable_another_projects_flow(test_db) -> None:
    _seed_project(test_db)
    document = _document()
    document["retire_if_present"] = ["yoke-internal"]

    with pytest.raises(ValueError, match="belongs to another project"):
        reconcile_project_flows(test_db, "acme", document)

    assert test_db.execute(
        "SELECT status FROM deployment_flows WHERE id='yoke-internal'"
    ).fetchone()[0] == "active"
    assert test_db.execute(
        "SELECT COUNT(*) FROM deployment_flows WHERE project_id=%s",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()[0] == 0


def test_historical_run_freezes_definition_but_not_status(test_db) -> None:
    _seed_project(test_db)
    reconcile_project_flows(test_db, "acme", _document())
    insert_deployment_run(
        test_db,
        id="run-declaration-history",
        project="acme",
        flow="acme-production",
        status="succeeded",
        current_stage="complete",
    )
    changed = deepcopy(_document())
    changed["flows"][0]["description"] = "A rewritten definition"
    with pytest.raises(ValueError, match="historical run"):
        reconcile_project_flows(test_db, "acme", changed)

    disabled = deepcopy(_document())
    disabled.pop("default_flow")
    disabled["flows"][0]["status"] = "disabled"
    result = reconcile_project_flows(test_db, "acme", disabled)
    assert result["updated"] == ["acme-production"]


def test_invalid_default_rolls_back_all_new_definitions(test_db) -> None:
    _seed_project(test_db)
    document = _document()
    document["default_flow"] = "acme-missing"

    with pytest.raises(ValueError, match="is not a flow"):
        reconcile_project_flows(test_db, "acme", document)

    assert test_db.execute(
        "SELECT COUNT(*) FROM deployment_flows WHERE project_id=%s",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()[0] == 0


def test_preview_validates_without_persisting_any_rows(test_db) -> None:
    _seed_project(test_db)

    result = reconcile_project_flows(
        test_db,
        "acme",
        _document(),
        preview_only=True,
    )

    assert result["preview_only"] is True
    assert result["created"] == ["acme-production", "acme-internal"]
    assert result["default_flow_updated"] is False
    assert test_db.execute(
        "SELECT COUNT(*) FROM deployment_flows WHERE project_id=%s",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM project_structure WHERE project_id=%s",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()[0] == 0


def test_default_write_failure_rolls_back_flow_definitions(
    test_db, monkeypatch,
) -> None:
    _seed_project(test_db)

    def _refuse_default(*_args, **_kwargs):
        raise RuntimeError("project structure write unavailable")

    monkeypatch.setattr(
        "yoke_core.domain.deploy_defaults.set_default_flow_on_connection",
        _refuse_default,
    )
    with pytest.raises(RuntimeError, match="write unavailable"):
        reconcile_project_flows(test_db, "acme", _document())

    assert test_db.execute(
        "SELECT COUNT(*) FROM deployment_flows WHERE project_id=%s",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM project_structure "
        "WHERE project_id=%s AND family='deploy_defaults'",
        (resolve_project_id(test_db, "acme"),),
    ).fetchone()[0] == 0


def test_document_shape_rejects_unknown_fields_before_writes() -> None:
    document = _document()
    document["flows"][0]["consumer_special_case"] = True
    with pytest.raises(ValueError, match="unknown keys"):
        normalize_document(document)


def test_alternative_flows_may_govern_the_same_migration_model(test_db) -> None:
    _seed_project(test_db)
    settings = json_helper.dumps_compact({
        "default_model": "primary",
        "models": {"primary": {}},
    })
    test_db.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, config, settings, created_at) "
        "VALUES (%s, 'migration_model', %s, %s, '2026-01-01T00:00:00Z')",
        (resolve_project_id(test_db, "acme"), settings, settings),
    )
    test_db.commit()
    shared_gate = {
        "kind": "migration_apply",
        "model_name": "primary",
        "lifecycle_phase": "implementing",
    }
    document = _document()
    for flow in document["flows"]:
        flow["stages"].insert(0, shared_gate)

    result = reconcile_project_flows(test_db, "acme", document)

    assert result["created"] == ["acme-production", "acme-internal"]
