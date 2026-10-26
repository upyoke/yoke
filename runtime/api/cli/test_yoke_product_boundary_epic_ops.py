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
        "yoke workflow-item epic-task get": "workflow_item.epic_task.get",
        "yoke workflow-item epic-task simulation-get": "workflow_item.epic_task.simulation_get",
        "yoke workflow-item epic-task history-insert": "workflow_item.epic_task.history_insert",
        "yoke workflow-item epic-dispatch-chain get": "workflow_item.epic_dispatch_chain.get",
        "yoke workflow-item epic-dispatch-chain list": "workflow_item.epic_dispatch_chain.list",
        "yoke workflow-item epic-dispatch-chain update": "workflow_item.epic_dispatch_chain.update",
        "yoke workflow-item epic-dispatch-chain refresh-activation": "workflow_item.epic_dispatch_chain.refresh_activation",
        "yoke conduct epic-task update-status": "conduct.epic_task.update_status",
        "yoke conduct epic proceed-triage-handoff": "conduct.epic.proceed_triage_handoff",
    }
    for command, function_id in expected.items():
        row = rows[command]
        assert row.function_id == function_id
        assert row.disposition == inventory.HTTPS_RELAY
        assert row.transport_branch == "https-relay"
