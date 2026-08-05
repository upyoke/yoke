"""CLI coverage for deployment inventory and progress inspection."""

from __future__ import annotations

from unittest.mock import patch

from yoke_cli.commands.adapters.deployment_inspection import (
    deployment_flows_list,
    deployment_runs_find_by_item,
    deployment_runs_stages,
)


def test_deployment_inspection_adapters_build_typed_requests() -> None:
    calls = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    with patch(
        "yoke_cli.commands.adapters.deployment_inspection.dispatch_and_emit",
        side_effect=_dispatch,
    ):
        assert deployment_flows_list(["--project", "yoke", "--include-disabled"]) == 0
        assert deployment_runs_find_by_item(["YOK-711", "--status", "succeeded"]) == 0
        assert deployment_runs_stages(["run-20260616-001"]) == 0

    assert calls[0]["function_id"] == "deployment_flows.list"
    assert calls[0]["payload"] == {"project": "yoke", "include_disabled": True}
    assert calls[1]["function_id"] == "deployment_runs.find_by_item"
    assert calls[1]["target"].item_ref == "YOK-711"
    assert calls[1]["payload"] == {"status": "succeeded"}
    assert calls[2]["function_id"] == "deployment_runs.stages"
    assert calls[2]["target"].workflow_run_id == "run-20260616-001"


def test_deployment_inspection_registry_entries() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("deployment-flows", "list")][0] == (
        "deployment_flows.list"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "find-by-item")][0] == (
        "deployment_runs.find_by_item"
    )
    assert SUBCOMMAND_REGISTRY[("deployment-runs", "stages")][0] == (
        "deployment_runs.stages"
    )
