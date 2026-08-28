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


def test_the_profile_always_carries_a_governed_database_box():
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md")
    assert "### The governed-database box" in text
    # Every outcome is named; none is a silent default.
    assert "A governed model, declarable now" in text
    assert "A governed model, attached later" in text
    assert "No Yoke-governed database" in text
    assert "Undecided" in text
    # An undecided box lands on the existing failure floor.
    assert "human-interview=blocked" in text
    # The confirmation evidence records which answer was chosen.
    assert "governed database {declare-now|attach-later|none}" in text


def test_the_declaration_step_names_every_row_status_it_writes():
    text = _read(ONBOARD_DIR / "governed-database.md")
    for status in ("configured", "deferred", "not-needed", "blocked"):
        assert f"migration-model-setup={status}" in text
    assert "--evidence migration-model-setup=" in text
    assert "--blocker migration-model-setup=" in text


def test_no_governed_database_is_taught_as_a_first_class_answer():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert "keeps its DB claim at `none`" in text
    assert "correct and expected answer, not" in text
    assert "Nothing further is needed to finish onboarding." in text


def test_the_step_refuses_shapes_the_capability_validator_would_reject():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert "yoke projects capability-settings get --project {project} --cap-type migration_model" in text
    assert "yoke projects capability-settings set --project {project} --cap-type migration_model" in text
    for kind in ("sqlite_file", "worktree_local_sqlite", "postgres",
                 "external_validation", "governed_migration_module", "mysql"):
        assert kind in text


def test_rehearsal_is_taught_as_authorship_not_an_onboard_apply():
    text = _read(ONBOARD_DIR / "governed-database.md")
    assert "Onboard never applies a migration and never rehearses one." in text
    assert "yoke migration rehearse --help" in text
    # The HTTPS refusal is restated as correct, not relaxed.
    assert "refuses an HTTPS product connection" in text
    assert "that refusal is correct" in text


def test_the_router_lists_the_declaration_file_and_row_for_step_five():
    text = _read(ONBOARD_DIR / "SKILL.md")
    assert "[governed-database.md](governed-database.md)" in text
    assert f"`{ROW_ID}`" in text
    # The skip predicate reads live state rather than re-asking.
    assert "declared `migration_model` capability or a terminal" in text
