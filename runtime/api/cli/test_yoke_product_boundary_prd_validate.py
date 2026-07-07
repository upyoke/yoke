"""Product-boundary coverage for the PRD validation readiness wrapper."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]
DESIGN_CHECKS = ".agents/skills/yoke/shepherd/design-checks.md"
PLAN_HANDOFF = ".agents/skills/yoke/shepherd/plan-handoff.md"


def test_prd_validate_inventory_row_is_https_relay() -> None:
    rows = {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }

    row = rows["yoke readiness prd-validate"]
    assert row.function_id == "readiness.prd_validate.run"
    assert row.disposition == inventory.HTTPS_RELAY
    assert row.import_edges == ()


def test_shepherd_prd_validate_recipes_no_longer_drift() -> None:
    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)
    rows = [
        row for row in audit.surfaces
        if row.source in {DESIGN_CHECKS, PLAN_HANDOFF}
        and "prd-validate" in row.recipe
    ]

    assert {row.source for row in rows} == {DESIGN_CHECKS, PLAN_HANDOFF}
    assert {
        (row.command_form, row.function_id, row.drift_type)
        for row in rows
    } == {(
        "yoke readiness prd-validate",
        "readiness.prd_validate.run",
        None,
    )}
    assert not [
        row for row in audit.surfaces
        if row.source in {DESIGN_CHECKS, PLAN_HANDOFF}
        and row.drift_type == teaching.DRIFT_UNSANCTIONED_INTERNAL
        and "prd_validate" in row.recipe
    ]
