"""Onboarding test-profile guidance stays mirrored into the install bundle."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS


ONBOARD = SKILLS / "onboard"
BUNDLE = REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "install_bundle_tree"


def test_install_bundle_mirrors_the_canonical_guidance() -> None:
    for name in (
        "profile-and-scaffold.md",
        "hosting-and-environments.md",
        "verification-binding.md",
        "first-work.md",
    ):
        source = ONBOARD / name
        packaged = BUNDLE / ".agents" / "skills" / "yoke" / "onboard" / name
        assert packaged.read_bytes() == source.read_bytes()

    public_qa = REPO / "docs" / "public" / "verification" / "index.md"
    assert (
        BUNDLE / "docs" / "public" / "verification" / "index.md"
    ).read_bytes() == public_qa.read_bytes()
    assert (
        REPO / ".yoke" / "docs" / "verification" / "index.md"
    ).read_bytes() == public_qa.read_bytes()
