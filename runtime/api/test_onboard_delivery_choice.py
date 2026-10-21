"""Packaged delivery-choice skill files stay in sync and within size limits."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS


ONBOARD = SKILLS / "onboard"
USHER = SKILLS / "usher"
PACKAGED_SKILLS = (
    REPO
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "install_bundle_tree"
    / ".agents"
    / "skills"
    / "yoke"
)


def test_packaged_skill_contract_is_byte_exact() -> None:
    for relative in (
        Path("onboard/SKILL.md"),
        Path("onboard/profile-and-scaffold.md"),
        Path("onboard/hosting-and-environments.md"),
        Path("onboard/domain-and-deploy.md"),
        Path("usher/deploy.md"),
    ):
        assert (PACKAGED_SKILLS / relative).read_bytes() == (
            SKILLS / relative
        ).read_bytes()


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
