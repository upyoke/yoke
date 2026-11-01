"""Steering and onboarding publish the same vetted-dash handoff."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents/skills/yoke"
BUNDLE = ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree"


@pytest.mark.parametrize("skill", ("onboard", "steer"))
def test_skills_match_installed_bytes(skill):
    source = SKILLS / skill
    packaged = BUNDLE / ".agents/skills/yoke" / skill
    assert {p.name for p in source.glob("*.md")} == {
        p.name for p in packaged.glob("*.md")
    }
    for path in source.glob("*.md"):
        assert (packaged / path.name).read_bytes() == path.read_bytes()


def test_onboard_hands_off_without_filing_or_predefining_one_outcome():
    handoff = (SKILLS / "onboard/first-work.md").read_text()
    strategy = (SKILLS / "onboard/strategy-conversation.md").read_text()
    assert "Onboarding files no items" in handoff
    assert "first outcome" not in handoff
    assert "Steer gives each dash" in handoff
    assert "done test, flow and QA plan when filing" in handoff
    assert "goals and a high-level plan" in strategy
    assert "parallel dashes" in strategy


def test_steer_requires_vetting_and_approval_before_filing():
    rules = (SKILLS / "steer/SKILL.md").read_text()
    assert "File software work only as dashes" in rules
    assert "explicit operator workflow choices intact" in rules
    assert "correct dependency edges" in rules
    assert "Vet each proposal with a subagent for overengineering" in rules
    assert "simplify or delete" in rules
    assert "prefer no new DB fields or migrations" in rules
    assert "File only after explicit operator approval" in rules
    assert "every operator decision one at a time" in rules
    assert "simplest alternative" in rules
    assert "strategy doc current with what was filed" in rules
    loop = (SKILLS / "steer/loop.md").read_text()
    assert "As work lands, seek decisions" in loop
    assert "propose and vet that set" in loop
