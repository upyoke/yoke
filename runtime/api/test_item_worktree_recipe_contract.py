"""Recipe contracts for canonical item-owned worktree lanes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[2]
SOURCE_SKILLS = REPO_ROOT / ".agents" / "skills" / "yoke"
PACKAGED_SKILLS = (
    REPO_ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "install_bundle_tree"
    / ".agents"
    / "skills"
    / "yoke"
)
SOURCE_FUNCTION_REFERENCE = (
    REPO_ROOT / ".yoke" / "docs" / "db-reference" / "functions.md"
)
PACKAGED_FUNCTION_REFERENCE = (
    REPO_ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "install_bundle_tree"
    / ".yoke"
    / "docs"
    / "db-reference"
    / "functions.md"
)
RECIPE_PATHS = (
    "advance/SKILL.md",
    "advance/finalize.md",
    "advance/browser-qa.md",
    "advance/project-e2e.md",
    "advance/worktree.md",
    "do/loop-followups.md",
    "usher/deploy.md",
    "shared/tester-dispatch-template.md",
    "wrapup/SKILL.md",
)


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
@pytest.mark.parametrize("relative_path", RECIPE_PATHS)
def test_live_recipes_do_not_read_or_mutate_a_deleted_item_field(
    root: Path,
    relative_path: str,
) -> None:
    text = (root / relative_path).read_text()

    assert (
        re.search(
            r"yoke items get[^\n]*\bworktree\b",
            text,
        )
        is None
    )
    assert 'fields: ["worktree"]' not in text
    assert 'fields={"worktree": null}' not in text
    assert 'field="worktree"' not in text
    assert "worktree = NULL" not in text
    assert "SELECT id, title, worktree" not in text
    assert "worktree IS NOT NULL" not in text


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
def test_advance_and_qa_recipes_read_the_active_implementation_lane(
    root: Path,
) -> None:
    for relative_path in (
        "advance/SKILL.md",
        "advance/finalize.md",
        "advance/browser-qa.md",
        "advance/project-e2e.md",
    ):
        text = (root / relative_path).read_text()
        assert "yoke item-worktrees get" in text
        assert "--lane-role implementation --field branch" in text


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
def test_evidence_only_recovery_releases_active_lane_records(
    root: Path,
) -> None:
    for relative_path in ("advance/SKILL.md", "usher/deploy.md"):
        text = (root / relative_path).read_text()
        clean_check = text.find('git -C "$_wt_path" status --porcelain')
        release = text.find("yoke item-worktrees release YOK-{N} --all-active")
        assert clean_check != -1
        assert release != -1
        assert clean_check < release
        assert "--ignored=matching --untracked-files=all" in text[clean_check:release]
        assert "--reason evidence-only-recovery" in text[release:]
        assert "exactly one active implementation lane" in text
        assert "attestation" in text


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
def test_tester_reads_the_lane_through_the_registered_function(
    root: Path,
) -> None:
    text = (root / "shared/tester-dispatch-template.md").read_text()

    assert "`item_worktrees.get`" in text
    assert '`payload = {"lane_role": "implementation"}`' in text
    assert "`result.worktree.branch`" in text


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
def test_wrapup_reads_active_lanes_from_item_worktrees(root: Path) -> None:
    text = (root / "wrapup/SKILL.md").read_text()

    assert "yoke items overview list --json" in text
    assert "`result.rows`" in text
    assert "`worktrees` array is non-empty" in text
    assert "`public_ref`" in text
    assert "`branch`" in text
    assert "`lane_role`" in text
    assert "JOIN item_worktrees" not in text
    assert "- YOK-{N}: {title} ({status}, branch:" not in text


@pytest.mark.parametrize(
    "reference",
    (SOURCE_FUNCTION_REFERENCE, PACKAGED_FUNCTION_REFERENCE),
)
def test_function_reference_documents_transport_aware_lane_operations(
    reference: Path,
) -> None:
    text = reference.read_text()

    assert "`item_worktrees.create`" in text
    assert "sole policy-required default lane" in text
    assert "`item_worktrees.get`" in text
    assert "`item_worktrees.list`" in text
    assert "`item_worktrees.path_record`" in text
    assert "either local Postgres or HTTPS" in text
    assert "lane-id/branch stale-state preconditions" in text
    assert "`item_worktrees.release`" in text
    assert "fresh clean-lane attestation" in text
    assert "modified tracked, untracked, or ignored files" in text


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
def test_blitz_registers_explicit_additional_lanes(root: Path) -> None:
    text = (root / "blitz/SKILL.md").read_text()

    assert "yoke item-worktrees create ITEM --lane-role worker --branch BRANCH" in text
    assert "--lane-role integration" in text
    assert "rerun the ordinary worktree preparation" in text
    assert "yoke item-worktrees list ITEM --json" in text
    assert "over either HTTPS or machine-local" in text


@pytest.mark.parametrize("root", (SOURCE_SKILLS, PACKAGED_SKILLS))
def test_terminal_handoff_releases_claims_before_idle_hook_cleanup(
    root: Path,
) -> None:
    advance = (root / "advance/SKILL.md").read_text()
    followups = (root / "do/loop-followups.md").read_text()

    assert "yoke claims work release --all-mine" in advance
    assert "yoke claims work release --all-mine" in followups
    assert "Stop and SessionEnd never release active claims" in followups
    assert "closes only an already claim-free session" in followups
    assert "HarnessSessionEndReleasedClaims" not in followups
