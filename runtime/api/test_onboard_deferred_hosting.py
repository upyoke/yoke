"""Regression coverage for onboarding without a Yoke-managed host."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS


ONBOARD = SKILLS / "onboard"
PACKAGED_ONBOARD = (
    REPO
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "install_bundle_tree"
    / ".agents"
    / "skills"
    / "yoke"
    / "onboard"
)


def test_packaged_onboard_contract_is_byte_exact() -> None:
    for name in (
        "SKILL.md",
        "hosting-and-environments.md",
        "domain-and-deploy.md",
    ):
        canonical = ONBOARD / name
        packaged = PACKAGED_ONBOARD / name
        assert packaged.read_bytes() == canonical.read_bytes()


def test_claimed_files_stay_below_the_authored_file_limit() -> None:
    paths: tuple[Path, ...] = (
        ONBOARD / "SKILL.md",
        ONBOARD / "hosting-and-environments.md",
        ONBOARD / "domain-and-deploy.md",
        Path(__file__),
    )
    for path in paths:
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 350, path
