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
    assert (
        "Delivery: persistent environment (needs hosting), merge-only, or no default."
        in text
    )


def test_no_host_merge_only_branch_creates_a_runless_default() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    merge_only = " ".join(
        _between(text, "- **Merge-only:**", "- **No default:**").split()
    )

    assert "two `auto` stages, `merged` and `complete`" in merge_only
    assert "no tier or environment" in merge_only
    assert "`stage_kind: execution`" in merge_only
    assert "`yoke deployment-flows get FLOW target_tier` must read `none`" in merge_only
    assert "site" not in merge_only


def test_no_default_branch_clears_and_verifies_the_attachment() -> None:
    text = _read(ONBOARD / "hosting-and-environments.md")
    no_default = _between(text, "- **No default:**", "\n\n")

    assert "remove the project `deploy_defaults`" in no_default
    assert "the read must print nothing" in no_default


def test_usher_routes_registered_empty_tier_without_starting_a_run() -> None:
    text = _read(USHER / "deploy.md")
    route_a = _between(text, "Route A", "Route B:")

    assert "only for a flow that delivers nothing" in route_a
    assert "exit 7: use Route B" in route_a
    assert "deployment-runs start-for-item" not in route_a
    assert "done-transition -- PREFIX-N --skip-deploy" in route_a


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

    assert "carry `target_tier` NULL, create no deployment run" in " ".join(
        overview.split()
    )
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
