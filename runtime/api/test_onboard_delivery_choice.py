"""Packaged delivery-choice skill files stay in sync and within size limits."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import SKILLS


ONBOARD = SKILLS / "onboard"
USHER = SKILLS / "usher"


def test_authored_files_remain_below_the_hard_limit() -> None:
    paths = (
        ONBOARD / "SKILL.md",
        ONBOARD / "profile-and-scaffold.md",
        ONBOARD / "hosting-and-environments.md",
        ONBOARD / "domain-and-deploy.md",
        USHER / "deploy.md",
        Path(__file__),
    )
    for path in paths:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 350, path
