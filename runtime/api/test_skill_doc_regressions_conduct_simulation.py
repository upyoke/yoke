"""Doc regression for the conduct simulation-readback wiring.

Splits ``test-conduct-simulation-readback.sh`` into pytest assertions on the
shared ``persist-epic-simulation`` helpers as wired into the conduct skill.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
    _read_bundle,
)


# ---------------------------------------------------------------------------
# TestConductSimulationReadback
# ---------------------------------------------------------------------------


class TestConductSimulationReadback:
    """Conduct epic flow must use the shared ``persist-epic-simulation.sh``.

    Note: the original shell regression also scraped helper-script contents
    for ``check_epic_simulation_gate``, ``simulation-upsert``/``-get``, and
    exit-code contracts. Those helpers are now thin shims over
    ``yoke_core.domain.conduct_reviewed_handoff`` and
    ``yoke_core.domain.persist_simulation``; contract coverage lives in
    ``runtime/api/domain/test_conduct_reviewed_handoff.py`` and
    ``runtime/api/domain/test_persist_simulation.py``. This module only keeps
    the skill-doc wiring assertions — the part that would otherwise have no
    Python equivalent.
    """

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "simulation_gate": SKILLS / "conduct" / "simulation-gate.md",
            "simulation_gate_criteria": SKILLS / "conduct" / "simulation-gate-criteria.md",
            "simulation_gate_escalation": SKILLS / "conduct" / "simulation-gate-escalation.md",
            "autofix": SKILLS / "conduct" / "simulation-autofix.md",
            "autofix_patching": SKILLS / "conduct" / "simulation-autofix-patching.md",
            "autofix_verification": SKILLS / "conduct" / "simulation-autofix-verification.md",
        }

    def test_simulation_gate_initializes_local_result(self, docs):
        # Content split to simulation-gate-criteria.md
        text = _read_bundle(docs["simulation_gate"], docs["simulation_gate_criteria"])
        assert '_local_result=""' in text

    def test_simulation_gate_captures_local_clean_and_gaps(self, docs):
        # Content split to simulation-gate-criteria.md
        text = _read_bundle(docs["simulation_gate"], docs["simulation_gate_criteria"])
        assert '"SIMULATION: CLEAN"*) _local_result="CLEAN"' in text
        assert '"SIMULATION: GAPS FOUND"*) _local_result="GAPS FOUND"' in text

    def test_simulation_gate_uses_persist_helper(self, docs):
        # Content split across simulation-gate.md and simulation-gate-criteria.md
        text = _read_bundle(docs["simulation_gate"], docs["simulation_gate_criteria"])
        assert "yoke_core.domain.persist_simulation" in text
        assert "_persist_rc" in text

    def test_simulation_gate_has_no_inline_upsert(self, docs):
        # Check all simulation-gate split files: no inline Simulator->DB hops
        text = _read_bundle(
            docs["simulation_gate"],
            docs["simulation_gate_criteria"],
            docs["simulation_gate_escalation"],
        )
        assert (
            'echo "{simulator_output}" | sh "$SCRIPT_DIR/yoke-db.sh" epic simulation-upsert'
            not in text
        ), "inline simulation-upsert (shell form) must be absent from simulation-gate files"
        assert (
            'echo "{simulator_output}" | python3 -m yoke_core.cli.db_router epic simulation-upsert'
            not in text
        ), "inline simulation-upsert (Python form) must be absent from simulation-gate files"

    def test_simulation_gate_references_auto_handoff(self, docs):
        """simulation gate now relies on auto-handoff from persist_and_verify."""
        # Content split to simulation-gate-escalation.md
        text = _read_bundle(docs["simulation_gate"], docs["simulation_gate_escalation"])
        assert "auto-handoff" in text.lower() or "YOK-1391" in text

    def test_simulation_gate_proceed_branch_uses_python_handoff_owner(self, docs):
        """PROCEED triage must route through the Python-owned helper, now the
        wrapped `yoke conduct epic proceed-triage-handoff` command."""
        # Content split to simulation-gate-escalation.md
        text = _read_bundle(docs["simulation_gate"], docs["simulation_gate_escalation"])
        assert "yoke conduct epic proceed-triage-handoff" in text
        assert "Do NOT write `status reviewed-implementation` manually." in text
        assert "Reviewed-implementation handoff (same as CLEAN path)" not in text

    def test_simulation_gate_uses_dependencies_column_in_retry_queries(self, docs):
        # Dependency queries are in simulation-gate-criteria.md (compressed context assembly).
        # Real epic_tasks column is `dependencies` (NOT `depends_on`); the cleanup swept the
        # confabulated name out of conduct skill prose.
        text = _read_bundle(docs["simulation_gate"], docs["simulation_gate_criteria"])
        # The criteria file contains the query at least twice (Tier 2 and Tier 3 retry paths)
        assert text.count("SELECT task_num, title, dependencies FROM epic_tasks") >= 2
        assert "SELECT task_num, title, depends_on FROM epic_tasks" not in text

    def test_autofix_uses_persist_helper(self, docs):
        # Content split to simulation-autofix-patching.md and simulation-autofix-verification.md
        text = _read_bundle(docs["autofix"], docs["autofix_patching"], docs["autofix_verification"])
        assert "yoke_core.domain.persist_simulation" in text

    def test_autofix_has_no_inline_upsert(self, docs):
        # Check all autofix split files
        text = _read_bundle(docs["autofix"], docs["autofix_patching"], docs["autofix_verification"])
        assert (
            'yoke-db.sh" epic simulation-upsert "$_epic_id" "integration" < "$_sim_tmp"'
            not in text
        )
        assert (
            'db_router epic simulation-upsert "$_epic_id" "integration" < "$_sim_tmp"'
            not in text
        )


# ---------------------------------------------------------------------------
# TestConductSimulatorEpicAttestation
# ---------------------------------------------------------------------------


class TestConductSimulatorEpicAttestation:
    """Conduct simulator dispatch must require the two-line verdict block.

    Covers the epic-identity attestation contract: every dispatch and retry
    template the conduct skill teaches must require both the ``SIMULATION:``
    verdict line and the ``EPIC: YOK-{N}`` attestation line. The defensive
    bail must halt before any simulator invocation when ``_epic_id`` is empty.
    """

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "criteria": SKILLS / "conduct" / "simulation-gate-criteria.md",
            "escalation": SKILLS / "conduct" / "simulation-gate-escalation.md",
            "cleanup": SKILLS / "conduct" / "cleanup-report.md",
            "dispatch_prompts": SKILLS / "simulate" / "dispatch-prompts.md",
            "epic_flow": SKILLS / "simulate" / "epic-flow.md",
        }

    def test_standard_dispatch_requires_two_line_verdict(self, docs):
        text = _read(docs["criteria"])
        assert "EPIC: YOK-{N}" in text
        assert "two-line verdict block" in text

    def test_dispatch_prompts_all_require_two_line_verdict(self, docs):
        text = _read(docs["dispatch_prompts"])
        # Both plan and integration templates surface the requirement
        assert text.count("two-line verdict block") >= 3
        assert text.count("EPIC: YOK-{item_id}") >= 3

    def test_dispatch_prompts_name_exit_codes(self, docs):
        text = _read(docs["dispatch_prompts"])
        assert "exit 16" in text
        assert "exit 17" in text

    def test_criteria_documents_persist_exit_16_and_17(self, docs):
        text = _read(docs["criteria"])
        assert "16" in text and "wrong-epic body" in text
        assert "17" in text and "missing-epic body" in text

    def test_criteria_defensive_epic_id_bail(self, docs):
        text = _read(docs["criteria"])
        assert 'if [ -z "${_epic_id:-}" ]; then' in text
        assert "_epic_id lost between dispatches" in text

    def test_criteria_retry_tier_prompts_carry_two_line_block(self, docs):
        text = _read(docs["criteria"])
        # Formatting-omission retry, aggressive retry, and ultra-compressed
        # no-tool fallback each must instruct the simulator to emit the
        # two-line block. The literal `EPIC: YOK-${_epic_id}` is the
        # signature in retry prompts.
        assert text.count("EPIC: YOK-${_epic_id}") >= 3

    def test_criteria_classifies_missing_epic_as_formatting_omission(self, docs):
        text = _read(docs["criteria"])
        assert "EPIC: YOK-{N}` attestation line" in text

    def test_escalation_documents_pre_branch_halts(self, docs):
        text = _read(docs["escalation"])
        assert "Pre-Branch HALT Conditions" in text
        assert "_epic_id` is empty" in text or "_epic_id is empty" in text
        assert "exit 16" in text
        assert "exit 17" in text

    def test_cleanup_report_surfaces_wrong_epic_explicitly(self, docs):
        text = _read(docs["cleanup"])
        assert "wrong-epic body" in text
        assert "missing-epic body" in text
        assert "_epic_id lost between dispatches" in text

    def test_autofix_resimulation_prompts_require_epic_attestation(self):
        patching = _read(SKILLS / "conduct" / "simulation-autofix-patching.md")
        verification = _read(SKILLS / "conduct" / "simulation-autofix-verification.md")
        assert "EPIC: YOK-{_item_id}" in patching
        assert "EPIC: YOK-{_item_id}" in verification
        assert "exit 16" in patching
        assert "exit 17" in patching
        assert "exit 16" in verification
        assert "exit 17" in verification

    def test_autofix_attestation_failures_halt_not_gap_downgrade(self):
        patching = _read(SKILLS / "conduct" / "simulation-autofix-patching.md")
        verification = _read(SKILLS / "conduct" / "simulation-autofix-verification.md")
        assert "**If `_persist_rc` is 16 or 17" in patching
        assert "Return `AUTOFIX_HALTED`" in patching
        assert "not architectural gaps" in patching
        assert "**`_persist_rc` is 16 or 17:**" in verification
        assert "without treating the identity failure as an ordinary gap" in verification

    def test_compressed_context_includes_commit_boundary_evidence(self, docs):
        criteria = _read(docs["criteria"])
        prompts = _read(docs["dispatch_prompts"])
        combined = criteria + "\n" + prompts
        assert "Commit-Boundary Evidence" in combined
        assert "git log --oneline -- {file}" in combined
        assert "commit evidence unavailable: no affected file named" in combined
        assert "git log or git blame yourself" in combined

    def test_compressed_context_includes_private_shim_re_exports(self, docs):
        criteria = _read(docs["criteria"])
        prompts = _read(docs["dispatch_prompts"])
        combined = criteria + "\n" + prompts
        assert "Shim Re-Export Contracts" in combined
        assert "_BLOCKS" in combined
        assert "underscore-prefixed" in combined
        assert "shim import list is the source of truth" in combined

    def test_simulator_agent_requires_worktree_state_authority(self):
        text = _read(REPO / "runtime" / "agents" / "simulator.md")
        assert "Worktree-State Authority" in text
        assert "a task's resolved worktree checkout is the authority" in text
        assert "whether the item/epic has one worktree or many" in text
        assert "Main is the base/integration target, not evidence of unmerged task state" in text
        assert "report evidence missing instead of substituting main" in text

    def test_integration_prompts_anchor_actual_code_to_worktrees(self, docs):
        criteria = _read(docs["criteria"])
        prompts = _read(docs["dispatch_prompts"])
        flow = _read(docs["epic_flow"])
        autofix = _read_bundle(
            SKILLS / "conduct" / "simulation-autofix-patching.md",
            SKILLS / "conduct" / "simulation-autofix-verification.md",
        )
        combined = "\n".join((criteria, prompts, flow, autofix))
        assert combined.count("Worktree-State Authority") >= 5
        assert combined.count("Main is the base/integration target, not evidence of unmerged task state") >= 5
        assert combined.count("whether the item/epic has one worktree or many") >= 5
        assert "## Worktree Authorities" in prompts
        assert "## Worktree Authorities" in criteria
        assert "_worktree_list" in criteria
        assert "epic_dispatch_chains" in combined
        assert "worktree_path" in combined
        assert "report evidence missing instead of inspecting main as a substitute" in combined
