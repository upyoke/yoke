"""Onboard teaches the attested no-tests posture, not a silent empty gate."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARD_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard"
ADVANCE_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "advance"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_no_suite_branch_offers_three_named_choices():
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md")
    assert "No suite at all" in text
    assert "Scaffold a minimal suite" in text
    assert "Attest no-tests" in text
    assert "Stop." in text
    # The stop is the existing failure floor, not a new mechanism.
    assert "human-interview=blocked" in text


def test_the_attestation_recipe_is_a_copy_pasteable_command():
    text = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert "yoke qa no-tests attest --project {project} --reason" in text
    assert "yoke qa no-tests clear --project" in text
    # The refusal that pairs with the posture is named where it is taught.
    assert "command-ci" in text


def test_the_checklist_records_an_attestation_as_configured():
    # A reader must be able to tell an attested project from one nobody asked;
    # marking both `not-needed` would erase that difference.
    text = _read(ONBOARD_DIR / "hosting-and-environments.md")
    assert "attested no-tests posture, mark `verification-command-binding=configured`" in text
    assert "`deferred` for the operator who has not decided" in text


def test_advance_stops_teaching_the_prose_fallback_as_the_no_tests_story():
    text = _read(ADVANCE_DIR / "implementing" / "qa-seeding.md")
    assert "yoke qa no-tests attest" in text
    assert "seeded structurally" in text
