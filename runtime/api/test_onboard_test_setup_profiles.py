"""Regression coverage for honest onboarding test-profile mappings."""

from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
ONBOARD = REPO / ".agents" / "skills" / "yoke" / "onboard"
BUNDLE = REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "install_bundle_tree"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_profile_accepts_native_commands_and_review_only_suites() -> None:
    text = _read(ONBOARD / "profile-and-scaffold.md")

    for outcome in (
        "surveyed-command",
        "scaffold-suite",
        "review-only-suite",
        "explicit-skip",
    ):
        assert outcome in text
    for command in ("mvn -q -DskipITs test", "vendor/bin/phpunit", "xcodebuild"):
        assert command in text
    assert "separate `test_roots` entry" in text


def test_binding_keeps_non_actions_and_legacy_suites_honest() -> None:
    binding = _read(ONBOARD / "hosting-and-environments.md")
    seeding = _read(ONBOARD / "seed-work.md")

    assert "one keyed `put` operation per surveyed test tree" in binding
    assert "Jenkins, GitLab CI, Bitbucket" in binding
    assert "not `ci_workflow_file`" in binding
    assert "blocking `implementation_review` requirement" in binding
    assert "--qa-kind implementation_review" in seeding
    assert "--method-id command" in seeding
    assert "--blocking-mode non_blocking" in seeding
    assert '"command":"{legacy_argv}"' in seeding


def test_public_map_covers_non_pytest_and_multi_suite_realities() -> None:
    qa = _read(REPO / "docs" / "public" / "qa.md")
    archetypes = _read(REPO / "docs" / "install-onboard-archetypes" / "test-setup.md")

    for reality in (
        "Maven / JUnit",
        "PHPUnit",
        "XCTest",
        "Containerized",
        "Monorepo",
    ):
        assert reality in archetypes
    assert "Known-red / flaky" in archetypes
    assert "quick command may intentionally cover" in qa
    assert "non-blocking `command` case" in qa


def test_install_bundle_mirrors_the_canonical_guidance() -> None:
    for name in (
        "profile-and-scaffold.md",
        "hosting-and-environments.md",
        "seed-work.md",
    ):
        source = ONBOARD / name
        packaged = BUNDLE / ".agents" / "skills" / "yoke" / "onboard" / name
        assert packaged.read_bytes() == source.read_bytes()

    public_qa = REPO / "docs" / "public" / "qa.md"
    assert (BUNDLE / "docs" / "public" / "qa.md").read_bytes() == public_qa.read_bytes()
    assert (REPO / ".yoke" / "docs" / "qa.md").read_bytes() == public_qa.read_bytes()
