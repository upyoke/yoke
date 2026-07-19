"""CLI and refresh coverage for project-owned flow declarations."""

from __future__ import annotations

import json
from unittest.mock import patch

from yoke_cli.project_install.deployment_flows import (
    preflight_project_flow_declaration,
    sync_project_flow_declarations_for_write,
)
from yoke_contracts.api.function_call import FunctionCallResponse
from runtime.api.cli.test_yoke_operations_cli_deployment import (
    _CAPTURED_REQUESTS,
    _run_capture,
    _stub_ok,
)


def _declaration() -> dict:
    return {
        "schema": 1,
        "flows": [
            {
                "id": "acme-internal",
                "name": "Internal",
                "stages": [{"name": "complete", "executor": "auto"}],
            }
        ],
    }


def test_registry_maps_reconcile_project() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert (
        SUBCOMMAND_REGISTRY[("deployment-flows", "reconcile-project")][0]
        == "deployment_flows.reconcile_project"
    )


def test_flow_declaration_dispatches_project_owned_document(tmp_path) -> None:
    _CAPTURED_REQUESTS.clear()
    declaration = _declaration()
    path = tmp_path / "deployment-flows.json"
    path.write_text(json.dumps(declaration), encoding="utf-8")

    rc, _out, _err = _run_capture(
        _stub_ok,
        "deployment-flows",
        "reconcile-project",
        "acme",
        str(path),
    )

    assert rc == 0
    request = _CAPTURED_REQUESTS[-1]
    assert request.function == "deployment_flows.reconcile_project"
    assert request.target.project_id == "acme"
    assert request.payload == declaration


def test_flow_declaration_preview_is_read_only(tmp_path) -> None:
    _CAPTURED_REQUESTS.clear()
    declaration = _declaration()
    path = tmp_path / "deployment-flows.json"
    path.write_text(json.dumps(declaration), encoding="utf-8")

    rc, _out, _err = _run_capture(
        _stub_ok,
        "deployment-flows",
        "reconcile-project",
        "acme",
        str(path),
        "--preview",
    )

    assert rc == 0
    assert _CAPTURED_REQUESTS[-1].options == {"preview_only": True}


def test_project_refresh_materializes_nonempty_declaration(tmp_path) -> None:
    declaration = _declaration()
    path = tmp_path / ".yoke" / "deployment-flows.json"
    path.parent.mkdir()
    path.write_text(json.dumps(declaration), encoding="utf-8")
    response = FunctionCallResponse(
        success=True,
        function="deployment_flows.reconcile_project",
        version="v1",
        result={"created": ["acme-internal"]},
    )

    with patch(
        "yoke_cli.project_install.deployment_flows.dispatch_declaration",
        return_value=response,
    ) as dispatch:
        result = sync_project_flow_declarations_for_write(
            repo_root=tmp_path,
            project="acme",
        )

    dispatch.assert_called_once_with(
        project="acme",
        declaration=declaration,
        session_id=None,
    )
    assert result["created"] == ["acme-internal"]


def test_project_refresh_preflights_before_materializing(tmp_path) -> None:
    declaration = _declaration()
    prepared = (tmp_path / ".yoke" / "deployment-flows.json", declaration)
    response = FunctionCallResponse(
        success=True,
        function="deployment_flows.reconcile_project",
        version="v1",
        result={"preview_only": True},
    )

    with patch(
        "yoke_cli.project_install.deployment_flows.dispatch_declaration",
        return_value=response,
    ) as dispatch:
        preflight_project_flow_declaration(
            project="acme",
            prepared=prepared,
        )

    dispatch.assert_called_once_with(
        project="acme",
        declaration=declaration,
        session_id=None,
        preview_only=True,
    )
