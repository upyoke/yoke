"""Onboard asks about a governed database, and records "none" as a real answer."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.onboard_checklist import (
    LAYER_CAPABILITY,
    ROW_SPECS,
    STATUS_NOT_NEEDED,
    TERMINAL_STATUSES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARD_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard"

ROW_ID = "migration-model-setup"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def test_the_profile_always_asks_the_governed_database_question():
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md")
    # Every outcome is named; none is a silent default.
    assert "Database: declare now, attach later, none." in text
    # An undecided box lands on the existing failure floor.
    assert "`human-interview=blocked`" in text


def test_the_declaration_step_names_its_row_and_answers():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert f"`{ROW_ID}`" in text
    assert "`deferred`" in text
    assert "`not-needed`" in text
    # configured and blocked writes use the shared row recipes.
    rows = _read(ONBOARD_DIR / "run-and-rows.md")
    assert "--evidence {row}=" in rows
    assert "--blocker {row}=" in rows


def test_no_governed_database_is_taught_as_a_first_class_answer():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert "item DB claims stay `none`" in text


def test_the_step_declares_only_validator_accepted_shapes():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert "`migration_model` capability" in text
    assert "`sqlite_file` or `postgres`" in text
    assert "(../../../../.yoke/docs/databases/migration-model.md)" in text
    model_doc = _read(REPO_ROOT / ".yoke" / "docs" / "databases" / "migration-model.md")
    for kind in (
        "sqlite_file",
        "worktree_local_sqlite",
        "external_validation",
        "governed_migration_module",
    ):
        assert kind in model_doc


def test_onboard_never_applies_or_rehearses_a_migration():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert "Onboard never applies or rehearses migrations." in text


def test_the_delivery_step_routes_to_the_declaration_file():
    text = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert "[governed-database.md](governed-database.md)" in text
