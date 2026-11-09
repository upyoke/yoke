"""Workflow definition sections remain reachable when the registry is large."""

from __future__ import annotations

import json
import shlex
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
                "description": f"Use {name} for work. Another sentence.",
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
            {
                "id": n + 1,
                "name": f"release-{n}",
                "description": "flow-detail " * 12,
                "status": "active" if n < 4 else "disabled",
                "target_environment": "prod",
            }
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


def test_default_roster_lists_workflows_gate_count_and_only_active_flows(capsys):
    assert read([], registry()) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert "dash  10  Use dash for work." in captured.out
    assert "blitz  10  Use blitz for work." in captured.out
    assert "Another sentence" not in captured.out
    assert "1 gates." in captured.out
    assert "4 active of 25" in captured.out
    assert "release-3  prod" in captured.out
    assert "release-4" not in captured.out
    assert "1  prod" not in captured.out.splitlines()
    assert "21 disabled flows hidden" in captured.out
    assert "history-" not in captured.out
    assert "flow-detail" not in captured.out


def test_every_roster_pointer_runs_with_original_project(capsys):
    assert read([], registry()) == 0
    roster = capsys.readouterr().out
    commands = [
        line.split(prefix, 1)[1]
        for line in roster.splitlines()
        for prefix in ("Details: ", "All flows: ")
        if prefix in line
    ]
    assert len(commands) == 4
    for command in commands:
        tokens = shlex.split(command)
        assert tokens[:6] == [
            "yoke", "workflows", "definition", "get", "--project", "example"
        ]
        assert read(tokens[6:], registry()) == 0
        detail = capsys.readouterr()
        assert f"## {tokens[-1]}" in detail.out
        assert not detail.err


@pytest.mark.parametrize(
    "heading, marker",
    [
        ("dash", "10 versions, current 10 (see `yoke workflows version list dash`)"),
        ("Gate catalog", "Claim required"),
        ("release-12", "flow-detail"),
        ("Flows", "release-24"),
    ],
)
def test_each_narrow_read_fits_and_excludes_other_sections(capsys, heading, marker):
    assert read(["--section", heading], registry()) == 0
    captured = capsys.readouterr()
    assert marker in captured.out
    assert "## blitz" not in captured.out
    if heading != "Flows":
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


def test_full_whole_read_retains_metadata_disabled_flows_and_history(capsys):
    assert read(["--full"], registry()) == 0
    captured = capsys.readouterr()
    assert not captured.err
    for marker in ("family: work-items", "history-10", "release-24", "Reviewer"):
        assert marker in captured.out
    assert "disabled flows hidden" not in captured.out


def test_roster_description_is_single_line_first_sentence_and_bounded(capsys):
    result = registry()
    result["workflows"][0]["description"] = "Long\n" + "word " * 100 + ". Next."
    assert read([], result) == 0
    roster = capsys.readouterr().out
    row = next(line for line in roster.splitlines() if line.startswith("dash  "))
    assert len(row.split("  ", 2)[2]) <= 80
    assert row.endswith("…")
    assert "Next." not in roster
