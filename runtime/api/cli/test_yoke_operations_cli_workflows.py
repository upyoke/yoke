"""Tests for the authoritative workflow-definition CLI read."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters.workflows_read import (
    workflows_current_set,
    workflows_definition_get,
    workflows_item_get,
    workflows_item_migrate,
    workflows_policy_defaults_publish,
    workflows_version_get,
    workflows_version_list,
)
from yoke_contracts.api.function_call import FunctionCallResponse


def test_human_output_renders_registry_rows_and_gate_catalog(capsys) -> None:
    response = FunctionCallResponse(
        success=True,
        function="workflows.definition.get",
        version="v1",
        result={
            "family": "work-items",
            "workflows": [
                {
                    "id": "issue",
                    "current_version": 1,
                    "current_version_id": 7,
                    "status": "active",
                    "definition": {
                        "stages": [
                            {
                                "id": "idea",
                                "gates": [{"id": "db_mutation"}],
                            }
                        ],
                    },
                }
            ],
            "gate_catalog": [
                {
                    "id": "db_mutation",
                    "owner": "engine",
                    "description": "DB mutation evidence is complete.",
                }
            ],
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


def test_item_get_builds_server_resolved_target_and_renders_pin(capsys) -> None:
    response = FunctionCallResponse(
        success=True,
        function="workflows.item.get",
        version="v1",
        result={
            "item_id": 42,
            "workflow_id": "issue",
            "workflow_version": 3,
            "workflow_version_id": 17,
            "status": "implementing",
            "worktree_policy": "single_implementation_lane",
        },
    )
    captured = {}

    def _dispatch(*, human_writer, **kwargs):
        captured.update(kwargs)
        human_writer(response, sys.stdout, sys.stderr)
        return 0

    with patch(
        "yoke_cli.commands.adapters.workflows_read.dispatch_and_emit",
        side_effect=_dispatch,
    ):
        assert workflows_item_get(["YOK-42"]) == 0

    assert captured["function_id"] == "workflows.item.get"
    assert captured["target"].public_ref == "YOK-42"
    assert capsys.readouterr().out.strip() == (
        "item-workflow|42|issue|3|17|implementing|single_implementation_lane"
    )


def test_item_migrate_preview_renders_compatibility_and_conflicts(capsys) -> None:
    response = FunctionCallResponse(
        success=True,
        function="workflows.item.migrate",
        version="v1",
        result={
            "preview": True,
            "conflicts": ["QA requirement 7 changed"],
            "after": {
                "workflow_id": "issue",
                "workflow_version": 5,
                "status": "implementing",
            },
        },
    )

    def _dispatch(*, human_writer, **_kwargs):
        human_writer(response, sys.stdout, sys.stderr)
        return 0

    with patch(
        "yoke_cli.commands.adapters.workflows_read.dispatch_and_emit",
        side_effect=_dispatch,
    ):
        assert workflows_item_migrate(["YOK-42", "--preview"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "item-workflow-preview|false|issue|5|implementing",
        "conflict|QA requirement 7 changed",
    ]


def test_current_set_and_item_migrate_build_typed_payloads() -> None:
    calls = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    with patch(
        "yoke_cli.commands.adapters.workflows_read.dispatch_and_emit",
        side_effect=_dispatch,
    ), patch(
        "yoke_cli.commands.adapters.workflows_versions.dispatch_and_emit",
        side_effect=_dispatch,
    ):
        assert workflows_current_set([
            "issue", "2", "--expected-current-version", "1",
        ]) == 0
        assert workflows_item_migrate([
            "YOK-42", "--version", "2", "--preview",
        ]) == 0
        assert workflows_version_get(["issue", "1"]) == 0
        assert workflows_version_list(["dash"]) == 0
        assert workflows_policy_defaults_publish([
            "dash",
            "--path-claims", "on",
            "--expected-current-version", "1",
        ]) == 0
        assert workflows_policy_defaults_publish([
            "dash",
            "--file-budget", "on",
            "--expected-current-version", "2",
        ]) == 0
        assert workflows_policy_defaults_publish([
            "dash",
            "--path-survey", "off",
            "--expected-current-version", "3",
        ]) == 0

    assert calls[0]["function_id"] == "workflows.current.set"
    assert calls[0]["payload"] == {
        "workflow_id": "issue",
        "version": 2,
        "expected_current_version": 1,
    }
    assert calls[1]["function_id"] == "workflows.item.migrate"
    assert calls[1]["target"].public_ref == "YOK-42"
    assert calls[1]["payload"] == {"version": 2, "preview": True}
    assert calls[2]["function_id"] == "workflows.version.get"
    assert calls[2]["payload"] == {"workflow_id": "issue", "version": 1}
    assert calls[3]["function_id"] == "workflows.version.list"
    assert calls[3]["payload"] == {"workflow_id": "dash"}
    assert calls[4]["function_id"] == "workflows.policy_defaults.publish"
    assert calls[4]["payload"] == {
        "workflow_id": "dash",
        "expected_current_version": 1,
        "path_claims_default": True,
    }
    assert calls[5]["function_id"] == "workflows.policy_defaults.publish"
    assert calls[5]["payload"] == {
        "workflow_id": "dash",
        "expected_current_version": 2,
        "file_budget_default": True,
    }
    assert calls[6]["payload"] == {
        "workflow_id": "dash",
        "expected_current_version": 3,
        "path_survey_default": False,
    }


def test_item_migrate_help_teaches_operator_authority(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        workflows_item_migrate(["--help"])

    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "authority from an operator-started session" in help_text
    assert "must not change their own session mode" in help_text
    assert "--preview" in help_text
