"""Dash and Blitz skill distribution invariants."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]
BUNDLE = (
    ROOT
    / "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke"
)


def test_dash_skill_carries_the_end_to_end_execution_contract():
    content = (ROOT / ".agents/skills/yoke/dash/SKILL.md").read_text()
    for required in (
        "direct-workflow dash survey",
        "direct-workflow worktree prepare",
        "reviewing-implementation",
        "direct-workflow dash evidence",
        "direct-workflow dash escalate",
        "Registered work and path claims always win",
    ):
        assert required in content
    assert "/yoke idea" in content
    assert "does not route through `/yoke idea`" in content


def test_blitz_skill_carries_slice_and_document_completion_contract():
    content = (ROOT / ".agents/skills/yoke/blitz/SKILL.md").read_text()
    for required in (
        "strategy execution get",
        "direct-workflow blitz survey",
        "strategy coordination append",
        "what was completed",
        "what changed",
        "what remains",
        "parent strategy was reconciled",
        "doc_completion",
    ):
        assert required in content


def test_direct_workflow_skills_match_install_bundle():
    for skill in ("dash", "blitz"):
        canonical = ROOT / f".agents/skills/yoke/{skill}/SKILL.md"
        mirrored = BUNDLE / skill / "SKILL.md"
        assert mirrored.read_bytes() == canonical.read_bytes()
