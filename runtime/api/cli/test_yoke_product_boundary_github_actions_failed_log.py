"""Product-boundary coverage for the GitHub Actions failed-log wrapper."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_FAILED_LOG = "python3 -m yoke_core.domain.github_actions failed-log"


def test_failed_log_inventory_is_https_relay_safe() -> None:
    rows = {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    row = rows["yoke github-actions failed-log"]
    assert row.function_id == "github_actions.failed_log"
    assert row.disposition == inventory.HTTPS_RELAY
    assert row.transport_branch == "https-relay"
    assert row.capability_required == "project GitHub App auth"
    assert row.import_edges == ()

    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)
    by_form = {row.command_form: row for row in audit.surfaces}

    row = by_form["yoke github-actions failed-log"]
    assert row.resolution == "registered"
    assert row.function_id == "github_actions.failed_log"
    assert row.drift_type is None

    for surface in audit.surfaces:
        assert not surface.recipe.startswith(RAW_FAILED_LOG), surface
        assert surface.drift_type != teaching.DRIFT_UNSANCTIONED_INTERNAL or (
            not surface.recipe.startswith(RAW_FAILED_LOG)
        )
