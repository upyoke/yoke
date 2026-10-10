"""Regression contracts for native simulation receipts and bounded dispatch."""

import pytest

from runtime.api.skill_doc_regressions_test_helpers import REPO, SKILLS


def words(family, name):
    return " ".join((SKILLS / family / name).read_text().split())


@pytest.mark.parametrize(
    "family,name",
    [
        ("conduct", "simulation-gate-criteria.md"),
        ("conduct", "simulation-autofix-verification.md"),
        ("simulate", "epic-flow.md"),
    ],
)
def test_every_persistence_boundary_requires_exact_verified_receipt(family, name):
    text = words(family, name)
    for token in (
        "simulation-upsert",
        "--json",
        "verified=true",
        "requirement_id",
        "run_id",
        "verdict",
    ):
        assert token in text, (name, token)
    assert "identity" in text or "public_ref" in text
    assert "uncertain write" in text.lower()
    assert "persist_" + "simulation" not in text


def test_initial_and_retry_dispatches_keep_public_identity():
    text = words("conduct", "simulation-gate-criteria.md")
    assert 'if [ -z "${_epic_ref:-}" ]; then' in text
    assert "_epic_ref lost between dispatches" in text
    assert "before every initial/retry" in text.lower()
    assert "two-line verdict block" in text
    assert "EPIC: PREFIX-{N}" in text
    assert text.count("EPIC: ${_epic_ref}") == 3
    assert "formatting_omission" in text and "context_exhaustion" in text
    assert "Exhaustion" in text and "HALTs" in text


def test_each_mode_requires_common_attestation_contract():
    text = words("simulate", "dispatch-prompts.md")
    assert "common contract AND exactly one mode" in text
    assert "EPIC: {public_ref}" in text
    for mode in (
        "Plan mode",
        "Standard integration mode",
        "Compressed integration mode",
    ):
        section = text.split("## " + mode, 1)[1].split("## ", 1)[0]
        assert "common contract" in section
    for token in (
        "Read-only",
        "do not edit or file work",
        "set -e",
        "previous error model",
        "failure tests",
        "Fix level: plan|code|mixed",
    ):
        assert token in text


def test_identity_and_readback_failures_preserve_diagnostics_and_halt():
    criteria = words("conduct", "simulation-gate-criteria.md")
    cleanup = words("conduct", "cleanup-report.md")
    escalation = words("conduct", "simulation-gate-escalation.md")
    for text in (criteria, cleanup, escalation):
        assert "wrong-epic body" in text.lower()
        assert "missing-epic body" in text.lower()
        assert "exact" in text
    assert "returned ids" in criteria
    assert "producer_unavailable" in criteria
    assert "Pre-Branch HALT Conditions" in escalation
    assert "Persistence is not an auto-handoff" in escalation


def test_clean_handoff_runs_parent_native_gates_before_transition_and_release():
    text = words("conduct", "simulation-gate-escalation.md")
    gate = text.index("Complete each still-owed native case")
    transition = text.index("yoke lifecycle transition")
    verify = text.index("Verify the returned/live stage equals HANDOFF_STAGE")
    release = text.index("yoke claims work release")
    assert gate < transition < verify < release
    for token in (
        "--from LIVE_STAGE",
        "--to HANDOFF_STAGE",
        "--json",
        "current candidate",
        "declared policy",
        "holder-list",
        "Failed release is incomplete handoff",
    ):
        assert token in text
    assert "Do NOT write `status reviewed-implementation` manually" in text
    assert "yoke conduct epic proceed-triage-handoff" in text


def test_nonblocking_report_never_invents_clean_or_handoff():
    loop = words("simulate", "autofix-loop.md")
    entry = loop.split("## Classify and gather", 1)[0]
    for token in (
        "NOTE-only gaps return `AUTOFIX_NOT_REQUIRED`",
        "No CRITICAL gaps and recommendation `PROCEED`",
        "including WARNING gaps",
        "does not write a passing verdict",
        "after each persisted `GAPS FOUND` re-simulation",
    ):
        assert token in entry
    escalation = words("conduct", "simulation-gate-escalation.md")
    branch = escalation.split("**If auto-fix returns `AUTOFIX_NOT_REQUIRED`:**", 1)[1]
    assert "registered PROCEED triage write" in branch
    assert "simulation_nonblocking_recommendation_unresolved" in branch
    assert "Do not manufacture" in branch


def test_one_architect_loop_and_one_code_amend_preserve_budgets():
    adapter = words("conduct", "simulation-autofix.md")
    loop = words("simulate", "autofix-loop.md")
    amend = words("conduct", "simulation-autofix-verification.md")
    assert "../simulate/autofix-loop.md" in adapter
    assert "--force-integration --auto-fix" in adapter
    assert 'DispatchDescriptor(role="architect")' not in adapter
    for token in (
        "iteration limit is **3**",
        "Never reset iteration",
        "simulation_fix_level_missing",
        "Only update task bodies",
        "simulation_fix_no_change",
        "simulation_fix_iterations_exhausted",
        "AUTOFIX_CODE_GAPS",
        "caller separately owns its gated lifecycle",
    ):
        assert token in loop
    assert "Maximum one amend cycle" in amend
    assert "no implementation retry" in amend
    assert "EPIC: {public_ref}" in amend
    assert "without treating the identity failure as an ordinary gap" in amend
    assert "returns `AUTOFIX_HALTED`" in loop
    assert "never repeat an uncertain write" in loop


def test_compressed_bundle_retains_private_exports_commit_proof_and_limits():
    criteria = words("conduct", "simulation-gate-criteria.md")
    prompt = words("simulate", "dispatch-prompts.md")
    for text in (criteria, prompt):
        for token in (
            "_BLOCKS",
            "Commit-Boundary Evidence",
            "commit evidence unavailable: no affected file named",
        ):
            assert token in text
        assert "source of truth" in text
    assert "SELECT task_num, title, dependencies FROM epic_tasks" in criteria
    assert "SELECT task_num, title, depends_on" not in criteria
    for token in (
        "at most 3 candidate gaps",
        "at most 5 selective file reads",
        "Forbidden: broad branch diffs",
        "git log/blame unless explicitly requested",
    ):
        assert token in prompt


def test_integration_authority_applies_to_both_modes_and_missing_evidence():
    prompt = words("simulate", "dispatch-prompts.md")
    assert "append to BOTH integration modes" in prompt
    assert "one lane or many" in prompt
    assert "Missing lane or supplied diff is missing evidence" in prompt
    for mode in ("Standard integration mode", "Compressed integration mode"):
        assert "integration authority" in prompt.split("## " + mode, 1)[1]
    criteria = words("conduct", "simulation-gate-criteria.md")
    assert "_worktree_list" in criteria
    assert "epic-dispatch-chain list" in criteria
    agent = " ".join((REPO / "runtime/agents/simulator.md").read_text().split())
    assert "a task's resolved worktree checkout is the authority" in agent
    assert "report evidence missing instead of substituting main" in agent
