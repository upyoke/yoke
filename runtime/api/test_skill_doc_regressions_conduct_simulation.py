"""Regression contracts for native simulation receipts and bounded dispatch."""

import pytest

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS


def words(family, name):
    return " ".join((SKILLS / family / name).read_text().split())


def simulator_role():
    return " ".join((REPO / "runtime/agents/simulator.md").read_text().split())


@pytest.mark.parametrize(
    "family,name",
    [
        ("conduct", "simulation-gate-criteria.md"),
        ("simulate", "epic-flow.md"),
    ],
)
def test_every_persistence_boundary_requires_verified_receipt(family, name):
    text = words(family, name)
    for token in ("simulation-upsert", "--json", "verified=true"):
        assert token in text, (name, token)
    assert "persist_" + "simulation" not in text


def test_uncertain_writes_are_read_back_never_repeated():
    criteria = words("conduct", "simulation-gate-criteria.md")
    assert "Uncertain write: read back, never rewrite" in criteria
    assert "simulation-get --epic PREFIX-N --phase integration" in criteria
    assert "use the returned verdict" in criteria
    assert "Never repeat an uncertain write" in words("simulate", "autofix-loop.md")


def test_dispatch_contract_requires_fix_level_and_read_only():
    text = words("simulate", "dispatch-prompts.md")
    for token in ("EPIC: {public_ref}", "Read-only", "Fix level: plan|code|mixed"):
        assert token in text
    role = simulator_role()
    assert "Failure Path Analysis" in role
    assert "Check failure tests" in role


def test_identity_or_receipt_failure_halts():
    escalation = words("conduct", "simulation-gate-escalation.md")
    assert "Identity or receipt failure: cleanup HALTED" in escalation


def test_clean_handoff_runs_parent_native_gates_before_transition_and_release():
    text = words("conduct", "simulation-gate-escalation.md")
    gate = text.index("Run each still-owed parent QA case")
    transition = text.index("yoke lifecycle transition")
    release = text.index("yoke claims work release")
    assert gate < transition < release
    for token in ("--from LIVE_STAGE", "--to HANDOFF_STAGE", "--json"):
        assert token in text
    assert "yoke conduct epic proceed-triage-handoff" in text


def test_nonblocking_report_never_invents_clean_or_handoff():
    loop = words("simulate", "autofix-loop.md")
    assert "NOTE-only, or no CRITICAL and `PROCEED`" in loop
    assert "return `AUTOFIX_NOT_REQUIRED` (not CLEAN)" in loop
    escalation = words("conduct", "simulation-gate-escalation.md")
    assert (
        "AUTOFIX_NOT_REQUIRED: branch 1 if PROCEED with zero CRITICAL, else halt"
        in escalation
    )


def test_one_architect_loop_and_one_code_amend_preserve_budgets():
    escalation = words("conduct", "simulation-gate-escalation.md")
    loop = words("simulate", "autofix-loop.md")
    amend = words("conduct", "simulation-autofix-verification.md")
    assert "../simulate/autofix-loop.md" in escalation
    assert "caller=conduct" in escalation
    for token in (
        "iteration limit is **3**",
        "Never reset iteration",
        "simulation_fix_level_missing",
        "Write back only what it changed",
        "simulation_fix_no_change",
        "simulation_fix_iterations_exhausted",
        "AUTOFIX_CODE_GAPS",
        "caller separately owns its gated lifecycle",
    ):
        assert token in loop
    assert "amend cycle (once)" in amend
    assert "one [loop](engineer-tester-loop.md) with no retry" in amend
    assert "FAIL: AUTOFIX_HALTED" in amend


def test_compressed_bundle_limits():
    prompt = words("simulate", "dispatch-prompts.md")
    assert "at most 3 candidate gaps" in prompt
    assert "at most 5 selective file reads" in prompt
    assert "log/blame unless asked" in simulator_role()


def test_integration_authority_applies_to_both_modes_and_missing_evidence():
    prompt = words("simulate", "dispatch-prompts.md")
    assert "each task's worktree_path and diff (main is only the base)" in prompt
    criteria = words("conduct", "simulation-gate-criteria.md")
    assert "Code authority is each task's registered worktree or diff, not main" in (
        criteria
    )
    assert "sim_force_standard_integration" in criteria
    agent = simulator_role()
    assert "a task's resolved worktree checkout is the authority" in agent
    assert "report evidence missing instead of substituting main" in agent
