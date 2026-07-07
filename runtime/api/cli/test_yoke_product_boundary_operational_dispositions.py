"""S0G operational command product-boundary dispositions."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import operation_inventory as ops
from yoke_cli import product_boundary_inventory as inventory


REPO_ROOT = Path(__file__).resolve().parents[3]


def _rows() -> dict[str, inventory.InventoryRow]:
    return {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }


def test_browser_qa_lifecycle_commands_are_client_local_helpers() -> None:
    rows = _rows()
    for shell_form in (
        "yoke qa browser setup",
        "yoke qa browser status",
    ):
        row = rows[shell_form]
        assert row.disposition == inventory.CLIENT_LOCAL_HELPER
        assert row.transport_branch == "client-local-tool"
        assert row.import_edges == ()
        entry = ops.lookup(shell_form)
        assert entry is not None
        assert entry.status == ops.PERMANENT
        assert entry.reason == ops.REASON_TOOL_SHAPED


def test_github_actions_v0_product_surface_is_wait_run_only() -> None:
    rows = _rows()
    wait_run = rows["yoke github-actions wait-run"]
    assert wait_run.disposition == inventory.HTTPS_RELAY
    assert wait_run.transport_branch == "https-relay"

    for shell_form in (
        "yoke github-actions check-ci",
        "yoke github-actions runners status",
        "yoke github-actions secret set",
        "yoke github-actions variable get",
        "yoke github-actions variable set",
    ):
        assert rows[shell_form].disposition == inventory.SOURCE_DEV_ADMIN


def test_doctor_product_surface_stays_https_relay() -> None:
    row = _rows()["yoke doctor run"]
    assert row.disposition == inventory.HTTPS_RELAY
    assert row.import_edges == ()
