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


def test_step_map_rechecks_the_live_hosting_branch() -> None:
    router = _read(ONBOARD / "SKILL.md")

    for state_pair in (
        "hosting-setup=verified\\|configured",
        "deferred\\|not-needed",
    ):
        assert state_pair in router
    assert "no-host default is empty" in router
    assert "current no-host branch recorded `domain-setup=not-needed`" in router
    assert "terminal `deferred\\|not-needed` still matches the live hosting row" in router


def test_persistent_recipes_exist_only_in_the_managed_host_branch() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    managed = _between(
        text,
        "### Hosting verified/configured: register the site and environments",
        "### Hosting deferred/not-needed: clear the project default",
    )
    no_host = _between(
        text,
        "### Hosting deferred/not-needed: clear the project default",
        "### Bind the confirmed test setup",
    )

    recipes = (
        "yoke projects site create",
        "yoke projects environment create",
        "yoke deployment-flows create",
        '"op":"put","family":"deploy_defaults"',
    )
    for recipe in recipes:
        assert recipe in managed
        assert recipe not in no_host
        assert text.count(recipe) == managed.count(recipe)
    assert "--target-tier persistent" in managed


def test_no_host_branch_clears_and_verifies_the_default() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    no_host = _between(
        text,
        "### Hosting deferred/not-needed: clear the project default",
        "### Bind the confirmed test setup",
    )

    remove = '"op":"remove","family":"deploy_defaults","attachment":"project"'
    readback = "yoke project-structure deploy-defaults get --project {project}"
    assert remove in no_host
    assert no_host.count(readback) == 2
    assert "final read must print nothing" in no_host
    assert "environment-registration=not-needed" in no_host
    assert "delivery-setup=not-needed" in no_host
    assert "delivery-setup=blocked" in no_host
    assert "then stop" in no_host


def test_later_verified_hosting_can_register_persistent_routes() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")

    assert "Prior `deferred` or `not-needed` values are not proof" in text
    assert "re-evaluates the live capability probe" in text
    assert "Choose exactly one branch" in text
    assert "Only this branch may register managed hosting" in text


def test_no_host_domain_and_deploy_rows_are_terminal() -> None:
    text = _read(ONBOARD / "domain-and-deploy.md")
    no_host = _between(
        text,
        "### Hosting deferred/not-needed: close the hosted rows",
        "### Hosting verified/configured: record the domain",
    )

    assert no_host.count("domain-setup=not-needed") == 2
    assert "infra-apply-first-deploy=deferred" in no_host
    assert "infra-apply-first-deploy=not-needed" in no_host
    assert "continue directly to step 8" in no_host
    assert "project default is empty" in no_host
    assert "no-host branch above does not enter this gate" in text


def test_empty_default_keeps_seeded_work_unassigned() -> None:
    text = _read(ONBOARD / "seed-work.md")

    assert "empty output means no flow — omit the flag" in text
    assert "When no flow applies, omit `--deployment-flow`" in text
    assert "never pass the literal string `none`" in text


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
