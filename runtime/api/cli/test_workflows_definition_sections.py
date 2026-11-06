"""Workflow definition sections remain reachable when the registry is large."""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.workflows_read import workflows_definition_get
from yoke_cli.transport.output_limit import read_output_scope
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import FunctionCallResponse


def registry():
    return {
        "family": "work-items",
        "workflows": [
            {
                "id": name,
                "current_version": 10,
                "definition": {"description": name * 1000},
                "versions": [
                    {"version": n, "published_reason": f"history-{n}"}
                    for n in range(1, 11)
                ],
            }
            for name in ("dash", "blitz")
        ],
        "gate_catalog": [
            {"id": "work_claim_activation", "description": "Claim required"}
        ],
        "flows": [
            {"name": f"release-{n}", "description": "flow-detail " * 120}
            for n in range(25)
        ],
        "flow_actor_names": {"1": "Reviewer"},
        "title_max_length": 100,
    }


def read(args, result):
    response = FunctionCallResponse(
        success=True,
        function="workflows.definition.get",
        version="v1",
        result=result,
    )

    def dispatch(*, human_writer, json_mode, payload, **kwargs):
        assert payload == {"project": "example"}
        return emit_response(response, human_writer=human_writer, json_mode=json_mode)

    args = ["--project", "example", *args]
    with (
        read_output_scope(
            args, response.function, ("yoke", "workflows", "definition", "get")
        ),
        patch(
            "yoke_cli.commands.adapters.workflows_read.dispatch_and_emit",
            side_effect=dispatch,
        ),
    ):
        return workflows_definition_get(args)


def test_oversized_registry_lists_every_workflow_gate_and_flow(capsys):
    assert read([], registry()) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "read_output_limit_exceeded" in captured.err
    for heading in (
        "dash",
        "blitz",
        "Gate catalog",
        "Flows",
        *(f"release-{n}" for n in range(25)),
    ):
        assert (
            f"--section '{heading}'" in captured.err
            or f"--section {heading}\n" in captured.err
        )


@pytest.mark.parametrize(
    "heading, marker",
    [
        ("dash", "10 versions, current 10 (see `yoke workflows version list dash`)"),
        ("Gate catalog", "Claim required"),
        ("release-12", "flow-detail"),
    ],
)
def test_each_narrow_read_fits_and_excludes_other_sections(capsys, heading, marker):
    assert read(["--section", heading], registry()) == 0
    captured = capsys.readouterr()
    assert marker in captured.out
    assert "## blitz" not in captured.out
    assert "### release-13" not in captured.out
    assert "history-1" not in captured.out
    assert not captured.err


def test_full_expands_history_without_mutating_response(capsys):
    result = registry()
    original = deepcopy(result)
    assert read(["--full", "--section", "dash"], result) == 0
    captured = capsys.readouterr()
    assert "versions:" in captured.out
    assert "history-10" in captured.out
    assert "10 versions, current" not in captured.out
    assert result == original


def test_json_preserves_complete_server_payload(capsys):
    result = registry()
    assert read(["--json"], result) == 0
    assert json.loads(capsys.readouterr().out)["result"] == result
