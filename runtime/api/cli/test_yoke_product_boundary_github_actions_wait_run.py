"""Product-boundary coverage for the GitHub Actions wait-run wrapper."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_WAIT_RUN = "python3 -m yoke_core.domain.github_actions wait-run"


def test_wait_run_inventory_is_https_relay_safe() -> None:
    rows = {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    row = rows["yoke github-actions wait-run"]
    assert row.function_id == "github_actions.wait_run"
    assert row.disposition == inventory.HTTPS_RELAY
    assert row.transport_branch == "https-relay"
    assert row.capability_required == "project GitHub capability/PAT"
    assert row.import_edges == ()


def test_structured_adapter_inventory_tracks_wait_run() -> None:
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        adapter_index,
    )

    entry = adapter_index()["github_actions.wait_run"]
    assert entry.read_shape is True
    assert entry.cli_invocation.startswith("yoke github-actions wait-run")


def test_conduct_teaching_uses_registered_wait_run_surface() -> None:
    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)
    by_form = {row.command_form: row for row in audit.surfaces}

    row = by_form["yoke github-actions wait-run"]
    assert row.resolution == "registered"
    assert row.function_id == "github_actions.wait_run"
    assert row.drift_type is None

    for surface in audit.surfaces:
        assert not surface.recipe.startswith(RAW_WAIT_RUN), surface
        assert surface.drift_type != teaching.DRIFT_UNSANCTIONED_INTERNAL or (
            not surface.recipe.startswith(RAW_WAIT_RUN)
        )
