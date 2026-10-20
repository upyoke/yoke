"""Onboard teaches the attested no-tests posture, not a silent empty gate."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ONBOARD_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "onboard"
IMPLEMENT_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "implement"


def _read(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_the_no_suite_branch_offers_named_choices():
    text = _read(ONBOARD_DIR / "profile-and-scaffold.md")
    assert "scaffold suite, review-only, attested no-tests, or stop" in text
    # The stop is the existing failure floor, not a new mechanism.
    assert "An undecided box writes `human-interview=blocked`" in text


def test_the_checklist_records_an_attestation_as_configured():
    # A reader must be able to tell an attested project from one nobody asked;
    # marking both `not-needed` would erase that difference.
    text = _read(ONBOARD_DIR / "verification-binding.md")
    assert "`yoke qa no-tests attest`, then write the row `configured`" in text


def test_no_tests_requirement_is_seeded_and_recorded_as_attested():
    doc = _read(REPO_ROOT / ".yoke" / "docs" / "verification" / "index.md")
    assert "seeds a blocking `no_tests_declared` requirement" in doc
    text = _read(IMPLEMENT_DIR / "implementing" / "test-and-record.md")
    assert "`no_tests_declared` agent-attested, never tests run" in text
