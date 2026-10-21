"""The onboard checklist contract carries the governed-database row."""

from __future__ import annotations

from yoke_contracts.onboard_checklist import (
    LAYER_CAPABILITY,
    ROW_SPECS,
    STATUS_NOT_NEEDED,
    TERMINAL_STATUSES,
)

ROW_ID = "migration-model-setup"


def test_the_checklist_contract_carries_the_governed_database_row():
    row = next(spec for spec in ROW_SPECS if spec.row_id == ROW_ID)
    assert row.layer == LAYER_CAPABILITY
    assert "governed database" in row.hint


def test_the_row_sorts_into_the_declaration_cluster_before_work_seeding():
    # Runs are read back ORDER BY step, so the step labels are the ordering.
    steps = {spec.row_id: spec.step for spec in ROW_SPECS}
    assert steps["verification-command-binding"] < steps[ROW_ID]
    assert steps[ROW_ID] < steps["work-seeding"]


def test_not_needed_is_a_recordable_terminal_answer():
    assert STATUS_NOT_NEEDED in TERMINAL_STATUSES
