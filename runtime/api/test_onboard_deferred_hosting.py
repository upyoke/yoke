"""Regression coverage for onboarding without a Yoke-managed host."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


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


def _between(text: str, start: str, end: str) -> str:
    assert start in text, f"missing section start: {start}"
    assert end in text, f"missing section end: {end}"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_hosting_branch_is_read_live_and_chosen_once() -> None:
    text = " ".join(_read(ONBOARD / "hosting-and-environments.md").split())

    assert "yoke aws admin-status --project {project} --json" in text
    assert "Pick exactly one branch" in text
    assert "a failed managed step never falls back to no-host" in text


def test_managed_and_merge_only_recipes_stay_in_their_branches() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    managed = _between(text, "- **Managed:**", "- **Merge-only:**")
    merge_only = _between(text, "- **Merge-only:**", "- **No default:**")
    no_default = _between(text, "- **No default:**", "\n\n")

    assert "register site and environments" in managed
    for branch in (merge_only, no_default):
        assert "register" not in branch
        assert "environments" not in branch


def test_no_host_domain_and_deploy_rows_are_terminal() -> None:
    text = " ".join(_read(ONBOARD / "domain-and-deploy.md").split())

    assert "No host: mark both rows not-needed or deferred; go to step 8." in text
    assert "Step 7, managed deploys only" in text


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
