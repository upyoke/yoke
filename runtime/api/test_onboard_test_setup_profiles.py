"""Regression coverage for honest onboarding test-profile mappings."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


ONBOARD = SKILLS / "onboard"
BUNDLE = REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "install_bundle_tree"


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_profile_accepts_native_commands_and_review_only_suites() -> None:
    text = _flat(_read(ONBOARD / "profile-and-scaffold.md"))
    hosting = _flat(_read(ONBOARD / "hosting-and-environments.md"))

    assert (
        "Tests: surveyed command, scaffold suite, review-only, attested no-tests, "
        "or stop." in text
    )
    assert "add one `test_roots` entry per test tree" in hosting


def test_binding_keeps_non_actions_and_legacy_suites_honest() -> None:
    binding = _flat(_read(ONBOARD / "verification-binding.md"))
    handoff = _flat(_read(ONBOARD / "first-work.md"))
    doc = _flat(_read(REPO / ".yoke" / "docs" / "verification" / "index.md"))

    assert "Jenkins, GitLab CI, Bitbucket Pipelines" in doc
    assert "they are not `ci_workflow_file` declarations" in doc
    assert "Declare an Actions test workflow" in binding
    assert (
        "Review-only suites add blocking `implementation_review` plus advisory "
        "`command`." in handoff
    )


def test_public_map_covers_non_pytest_and_multi_suite_realities() -> None:
    qa = _read(REPO / "docs" / "public" / "verification" / "index.md")
    archetypes = _read(REPO / "docs" / "install-onboard-archetypes" / "test-setup.md")

    for reality in (
        "Maven/JUnit",
        "PHPUnit",
        "XCTest",
        "Containerized",
        "Monorepo",
    ):
        assert reality in archetypes
    assert "Known-red/flaky" in archetypes
    assert "quick command may intentionally cover" in qa
    assert "non-blocking `command` case" in qa


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
