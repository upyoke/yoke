"""Product-boundary assertions for epic ops wrapper rows."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory


REPO_ROOT = Path(__file__).resolve().parents[3]


def _rows() -> dict[str, inventory.InventoryRow]:
    return {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }


def test_epic_ops_wrappers_are_https_relay_product_surfaces() -> None:
    rows = _rows()
    expected = {
        "yoke workflow-item epic-task get":
            "workflow_item.epic_task.get",
        "yoke workflow-item epic-task simulation-get":
            "workflow_item.epic_task.simulation_get",
        "yoke workflow-item epic-task file-add":
            "workflow_item.epic_task.file_add",
        "yoke workflow-item epic-task history-insert":
            "workflow_item.epic_task.history_insert",
        "yoke workflow-item epic-dispatch-chain get":
            "workflow_item.epic_dispatch_chain.get",
        "yoke workflow-item epic-dispatch-chain list":
            "workflow_item.epic_dispatch_chain.list",
        "yoke workflow-item epic-dispatch-chain update":
            "workflow_item.epic_dispatch_chain.update",
        "yoke workflow-item epic-dispatch-chain refresh-activation":
            "workflow_item.epic_dispatch_chain.refresh_activation",
        "yoke conduct epic-task update-status":
            "conduct.epic_task.update_status",
        "yoke conduct epic proceed-triage-handoff":
            "conduct.epic.proceed_triage_handoff",
    }
    for command, function_id in expected.items():
        row = rows[command]
        assert row.function_id == function_id
        assert row.disposition == inventory.HTTPS_RELAY
        assert row.transport_branch == "https-relay"


def test_structured_adapter_inventory_tracks_epic_ops() -> None:
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        adapter_index,
    )

    index = adapter_index()
    assert index["workflow_item.epic_task.simulation_get"].read_shape is True
    assert index["workflow_item.epic_task.file_add"].read_shape is False
    assert (
        index["workflow_item.epic_dispatch_chain.refresh_activation"].cli_invocation
        == "yoke workflow-item epic-dispatch-chain refresh-activation --epic N "
        "--worktree NAME --task-num N"
    )
    assert index["conduct.epic_task.update_status"].read_shape is False
    assert "yoke conduct epic-task update-status" in (
        index["conduct.epic_task.update_status"].cli_invocation
    )
