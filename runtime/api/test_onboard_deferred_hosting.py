"""Regression coverage for onboarding without a Yoke-managed host."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import SKILLS


ONBOARD = SKILLS / "onboard"


def test_claimed_files_stay_below_the_authored_file_limit() -> None:
    paths: tuple[Path, ...] = (
        ONBOARD / "SKILL.md",
        ONBOARD / "hosting-and-environments.md",
        ONBOARD / "domain-and-deploy.md",
        Path(__file__),
    )
    for path in paths:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 350, path
