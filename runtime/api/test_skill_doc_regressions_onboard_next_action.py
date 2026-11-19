"""Steering and onboarding publish the same vetted-dash handoff."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".agents/skills/yoke"


def test_onboard_hands_off_without_filing_or_predefining_one_outcome():
    handoff = (SKILLS / "onboard/first-work.md").read_text()
    strategy = (SKILLS / "onboard/strategy-conversation.md").read_text()
    assert "Onboarding files no items" in handoff
    assert "first outcome" not in handoff
    assert "Steer gives each dash" in handoff
    assert "done test and flow when filing" in handoff
    assert "a dash filed without a plan is verified" in handoff
    assert "by the quick command bound here" in handoff
    assert "approve starting the first wave" not in handoff
    assert "/yoke steer" in handoff
    assert "goals and a high-level plan" in strategy
    assert "parallel dashes" in strategy


def test_steer_vets_then_files_dashes_itself():
    rules = (SKILLS / "steer/SKILL.md").read_text()
    assert "File software work only as dashes" in rules
    assert "explicit operator workflow choices intact" in rules
    assert "`registered-command-quick` plan when one is registered" in rules
    assert "`--verification-method none` for none" in rules
    assert "Don't hand-roll waves" in rules
    assert "ordering need as a dependency edge" in rules
    assert "Vet each proposal with a subagent for overengineering" in rules
    assert "Vet every item before staffing it, whether you filed it or not" in rules
    assert "simplify or delete" in rules
    assert "prefer no new DB fields or migrations" in rules
    assert "File vetted dashes yourself" in rules
    assert "File only after explicit operator approval" not in rules
    assert "main-session flow" in rules
    assert "simplest alternative" in rules
    assert "strategy doc current with what was filed" in rules
    loop = (SKILLS / "steer/loop.md").read_text()
    assert "As work lands, seek decisions" in loop
    assert "vet and file that set" in loop
    assert "Vet any item you have not vetted yourself\nbefore launching it." in loop


def test_project_rules_file_decisions_as_requests():
    rules = (ROOT / "AGENTS.md").read_text()
    assert "yoke decision-requests ask" in rules
    assert "yoke decision-requests resolve" in rules
