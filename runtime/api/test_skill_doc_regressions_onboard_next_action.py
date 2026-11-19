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
    assert "goals and a high-level plan" in strategy
    assert "parallel dashes" in strategy


def test_steer_requires_vetting_and_approval_before_filing():
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
    assert "File only after explicit operator approval" in rules
    assert "simplest alternative" in rules
    assert "strategy doc current with what was filed" in rules
    loop = (SKILLS / "steer/loop.md").read_text()
    assert "As work lands, seek decisions" in loop
    assert "propose and vet that set" in loop
    assert "Vet any item you have not vetted yourself\nbefore launching it." in loop


def test_steer_keeps_the_users_finish_line_and_owns_done():
    rules = (SKILLS / "steer/SKILL.md").read_text()
    assert "strategy doc as given, under `# Objective` and `# Done when`" in rules
    assert "Never narrow the\n  scope or the finish line without the user's OK" in rules
    assert "a done test drawn from the doc's `# Done when`" in rules
    assert "close the\n  recorded `# Done when` are covered by the user's request" in rules
    seed = (SKILLS / "steer/scope-and-authority.md").read_text()
    assert "`# Objective`, `# Done when`, `# Frontier`" in seed
    loop = (SKILLS / "steer/loop.md").read_text()
    assert "Judge landed work against the doc's `# Done when`" in loop
    close_out = (SKILLS / "steer/close-out.md").read_text()
    assert "Every point of the doc's `# Done when` checked and met by you" in close_out
    assert "linked items all done" not in close_out
    assert "never sit beside `Nothing needs you.`" in close_out


def test_qa_compares_broadly_against_a_reference_or_oracle():
    rules = (ROOT / "docs/public/agents/rules.md").read_text()
    assert "When a reference implementation or oracle exists, compare against it\n  broadly" in rules
    assert "Cases you wrote yourself are not enough on their own." in rules
    verify = (SKILLS / "dash/verify.md").read_text()
    assert "When a reference implementation or oracle exists, test broadly against it" in verify
    assert "rules.md` → QA results" in verify


def test_project_rules_file_decisions_as_requests():
    rules = (ROOT / "AGENTS.md").read_text()
    assert "yoke decision-requests ask" in rules
    assert "yoke decision-requests resolve" in rules
