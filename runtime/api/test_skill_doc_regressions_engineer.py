"""Doc regressions for engineer agent + conduct submission-checks gate.

Ports ``test-engineer-submission-gate.sh`` plus the related conduct
dispatch-context wiring assertions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    AGENTS,
    REPO,
    SKILLS,
    _read,
    _read_bundle,
    _read_dispatch_context,
)


# ---------------------------------------------------------------------------
# TestEngineerSubmissionGate
# ---------------------------------------------------------------------------


class TestEngineerSubmissionGate:
    """Engineer agent + conduct docs must enforce the submission-checks block."""

    @pytest.fixture
    def docs(self) -> dict[str, Path]:
        return {
            "engineer": AGENTS / "yoke-engineer.md",
            "engineer_tester_loop": SKILLS / "conduct" / "engineer-tester-loop.md",
            "engineer_tester_dispatch": SKILLS / "conduct" / "engineer-tester-dispatch.md",
            "cleanup_report": SKILLS / "conduct" / "cleanup-report.md",
            "dispatch_context": SKILLS / "conduct" / "dispatch-context.md",
            "hooks_doc": REPO / "docs" / "hooks.md",
            "event_contract": REPO / "docs" / "event-contract.md",
            "event_catalog": REPO / "docs" / "event-catalog.md",
            "logging_standard": REPO / "docs" / "structured-logging-standard" / "agent-session-pattern.md",
        }

    def test_engineer_defines_submission_checks_block(self, docs):
        text = _read(docs["engineer"])
        assert "---SUBMISSION-CHECKS-START---" in text

    def test_engineer_requires_clean_worktree_pass(self, docs):
        text = _read(docs["engineer"])
        # Receipt format teaches the anchored shape used by the static-cwd
        # workspace lint.
        assert (
            "clean_worktree: PASS - git -C {worktree-path} status --porcelain is empty"
            in text
        )

    def test_engineer_explains_blocking_semantics(self, docs):
        text = _read(docs["engineer"])
        assert "result blocks the item from advancing to" in text

    def test_engineer_tester_loop_requires_submission_checks_block(self, docs):
        # Content split to engineer-tester-dispatch.md
        text = _read_bundle(docs["engineer_tester_loop"], docs["engineer_tester_dispatch"])
        assert "write a final progress note containing the required" in text

    def test_engineer_tester_loop_blocks_safety_net_commits(self, docs):
        # Content split to engineer-tester-dispatch.md
        text = _read_bundle(docs["engineer_tester_loop"], docs["engineer_tester_dispatch"])
        assert "Do NOT advance to" in text

    def test_engineer_tester_loop_records_note_count_baseline(self, docs):
        # Content split to engineer-tester-dispatch.md
        text = _read_bundle(docs["engineer_tester_loop"], docs["engineer_tester_dispatch"])
        assert "_progress_note_count_before=" in text

    def test_cleanup_report_resets_unmerged_generated_views(self, docs):
        text = _read(docs["cleanup_report"])
        assert "reset --quiet HEAD -- .yoke/BOARD.md" in text

    def test_cleanup_report_cleans_ignored_generated_views(self, docs):
        text = _read(docs["cleanup_report"])
        assert "clean -fdX -- .yoke/BOARD.md" in text

    def test_dispatch_context_requires_submission_checks_block(self, docs):
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "submission-receipt-get" in text

    def test_dispatch_context_records_per_item_baseline(self, docs):
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "_progress_note_count_before_{_id}=" in text

    def test_dispatch_context_blocks_safety_net_commits(self, docs):
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "Do NOT advance the item to" in text

    def test_engineer_deterministic_submission_trigger(self, docs):
        """AC-1: Engineer defines a concrete numeric cutoff.

        Cutoff value is pinned to the agent's current turn budget (300 → 30
        remaining = 10% submission window). If the budget changes, update
        both the agent prose and this assertion in the same commit.
        """
        text = _read(docs["engineer"])
        assert "30 or fewer turns remaining" in text

    def test_engineer_submission_mode_protocol(self, docs):
        """AC-2: Submission mode defined as finish-the-current-branch-state."""
        text = _read(docs["engineer"])
        assert "Submission Mode Protocol" in text
        assert "Forbidden in submission mode" in text

    def test_engineer_evidence_based_checklist(self, docs):
        """AC-3: Checks 1-2 are evidence-based, checks 3-4 mandatory."""
        text = _read(docs["engineer"])
        assert "evidence-based" in text.lower()
        assert "Mandatory final-pass check" in text

    def test_engineer_no_advisory_self_check(self, docs):
        """AC-1: Old advisory 'Self-check' and 'Last 10%' wording removed."""
        text = _read(docs["engineer"])
        assert "Self-check:" not in text
        assert "Last 10% of turns:" not in text

    def test_dispatch_context_submit_only_remediation(self, docs):
        """AC-4: Conduct defines submit-only remediation contract."""
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "submit-only remediation contract" in text.lower() or "Submit-only remediation contract" in text

    def test_dispatch_context_remediation_bounded(self, docs):
        """AC-5: Remediation bounded to 20 turns."""
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "max 20 turns" in text

    def test_agent_session_stopped_docs_describe_stop_reason(self, docs):
        """AC-9: stop_reason is documented across the live event docs."""
        assert "stop_reason" in _read(docs["hooks_doc"])
        assert "stop_reason" in _read(docs["event_contract"])
        assert "stop_reason" in _read(docs["event_catalog"])
        assert "stop_reason" in _read(docs["logging_standard"])

    def test_agent_session_stopped_logging_example_uses_agent_stop(self, docs):
        """structured logging example should match the live Python owner."""
        text = _read(docs["logging_standard"])
        assert '"hook": "agent_stop"' in text
        assert '"hook": "on-agent-stop.sh"' not in text
        assert "exit_reason" not in text
