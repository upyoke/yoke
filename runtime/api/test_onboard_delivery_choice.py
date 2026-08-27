"""Regression coverage for no-environment delivery choices."""

from __future__ import annotations

from pathlib import Path

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS, _read


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
ARCHETYPES = REPO / "docs" / "install-onboard-archetypes"


def _between(text: str, start: str, end: str) -> str:
    assert start in text, f"missing section start: {start}"
    assert end in text, f"missing section end: {end}"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_profile_confirms_exactly_one_named_delivery_outcome() -> None:
    text = _read(ONBOARD / "profile-and-scaffold.md")
    delivery = _between(text, "### The delivery box", "### The test-setup box")
    confirmation = _between(text, "### Confirm (stop 1 of 2)", "## Step 3")

    assert "Every profile names exactly one delivery outcome" in delivery
    assert "**Persistent environment**" in delivery
    assert "**Merge-only**" in delivery
    assert "local merge with no environment and no deployment pipeline or run" in delivery
    assert "**No default**" in delivery
    assert "offer only merge-only or no default" in delivery
    assert "delivery {persistent-environment|merge-only|no-default}" in confirmation
    assert "envs stage+prod" not in confirmation


def test_no_host_merge_only_branch_creates_a_runless_default() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    merge_only = _between(
        text,
        "### Hosting deferred/not-needed: create the confirmed merge-only default",
        "### Hosting deferred/not-needed: clear the project default",
    )

    assert "yoke deployment-flows create {project}-merge-only" in merge_only
    assert '[{"name":"merged","step_runner":"auto"},' in merge_only
    assert '{"name":"complete","step_runner":"auto"}]' in merge_only
    assert '"family":"deploy_defaults"' in merge_only
    assert "target-tier read must print nothing" in merge_only
    assert "delivery-setup=configured" in merge_only
    assert "no deployment run" in merge_only
    assert "yoke projects site create" not in merge_only
    assert "yoke projects environment create" not in merge_only
    create_command = merge_only.split(
        "yoke deployment-flows create", 1
    )[1].split("yoke deployment-flows get", 1)[0]
    assert "--target-tier" not in create_command
    assert "--environment" not in create_command


def test_no_default_branch_clears_and_verifies_the_attachment() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    no_default = _between(
        text,
        "### Hosting deferred/not-needed: clear the project default",
        "### Bind the confirmed test setup",
    )

    assert "confirmed delivery outcome is **no default**" in no_default
    assert '"op":"remove","family":"deploy_defaults"' in no_default
    assert no_default.count(
        "yoke project-structure deploy-defaults get --project {project}"
    ) == 2
    assert "delivery-setup=not-needed" in no_default


def test_usher_routes_registered_empty_tier_without_starting_a_run() -> None:
    text = _read(USHER / "deploy.md")
    grouping = _between(text, "## Step 8a", "## Step 8b")
    route_a = _between(text, "## Step 8b", "## Step 8c")

    assert "registered `deployment_flows.get` function" in grouping
    assert "successful empty target tier is merge-only" in grouping
    assert "names a registered flow whose\n  `target_tier` is empty" in grouping
    assert "registered merge-only items (no run)" in text
    assert "deployment-runs start-for-item" not in route_a
    assert "done-transition -- PREFIX-N --skip-deploy" in route_a


def test_no_host_router_and_handoff_accept_both_delivery_outcomes() -> None:
    router = _read(ONBOARD / "SKILL.md")
    handoff = _read(ONBOARD / "domain-and-deploy.md")

    expected = "registered merge-only default or an empty default"
    assert expected in router
    assert expected in handoff
    assert "no-host default is empty" not in router
    assert "project default is empty" not in handoff


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


def test_archetypes_teach_current_merge_only_delivery() -> None:
    overview = _read(REPO / "docs" / "install-onboard-archetypes.md")
    ledger = _read(ARCHETYPES / "gap-ledger.md")
    expected = {
        "A01-solo-idea-macos.md": "notebook-app-merge-only",
        "A04-small-team-paas-windows.md": "confirms **merge-only** delivery",
        "A05-agency-github-manual.md": "Dana chooses\n**no default**",
        "A09-small-team-appstore.md": "recognizes the empty\ntarget tier semantically",
        "A10-ainative-vibe-linux.md": "chooses **no default**",
        "A12-agency-greenfield.md": "confirms **merge-only**",
    }

    assert "any registered empty-tier flow" in overview
    assert "G-no-merge-only-default" not in ledger
    assert "any registered flow whose `target_tier` is\nempty" in ledger
    for name, phrase in expected.items():
        assert phrase in _read(ARCHETYPES / name)


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
