"""Tests for the authoritative workflow-definition CLI read."""

from __future__ import annotations

import sys
from unittest.mock import patch

from yoke_cli.commands.adapters.workflows_read import (
    workflows_definition_get,
)
from yoke_contracts.api.function_call import FunctionCallResponse


def test_human_output_renders_registry_rows_and_gate_catalog(capsys) -> None:
    response = FunctionCallResponse(
        success=True,
        function="workflows.definition.get",
        version="v1",
        result={
            "family": "work-items",
            "workflows": [{
                "id": "issue",
                "current_version": 1,
                "current_version_id": 7,
                "status": "active",
                "definition": {
                    "stages": [{
                        "id": "idea",
                        "gates": [{"id": "db_mutation"}],
                    }],
                },
            }],
            "gate_catalog": [{
                "id": "db_mutation",
                "owner": "engine",
                "description": "DB mutation evidence is complete.",
            }],
            "flows": [],
        },
    )

    def _dispatch(*, human_writer, **_kwargs):
        human_writer(response, sys.stdout, sys.stderr)
        return 0

    with patch(
        "yoke_cli.commands.adapters.workflows_read.dispatch_and_emit",
        side_effect=_dispatch,
    ):
        assert workflows_definition_get([]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "family|work-items",
        "workflow|issue|1|7|active|idea",
        "gate|issue|idea|db_mutation",
        "catalog-gate|db_mutation|engine|DB mutation evidence is complete.",
    ]
