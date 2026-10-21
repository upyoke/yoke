"""Doc regressions for engineer agent + conduct submission-checks gate.

Pins durable submission receipts, task attempt watermarks and review blocking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import (
    AGENTS,
    SKILLS,
    _read,
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
            "cleanup_report": SKILLS / "conduct" / "cleanup-report.md",
            "dispatch_context": SKILLS / "conduct" / "dispatch-context.md",
            "prompts": SKILLS / "conduct" / "dispatch-context-prompts.md",
            "submission_gates": SKILLS / "conduct" / "dispatch-context-gates.md",
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

    def test_conduct_requires_submission_checks_note(self, docs):
        prompts = " ".join(_read(docs["prompts"]).split())
        assert "Require the SUBMISSION-CHECKS progress note" in prompts

    def test_receipt_read_is_newer_than_attempt_note_count(self, docs):
        loop = " ".join(_read(docs["engineer_tester_loop"]).split())
        assert "per attempt record ATTEMPT_BASELINE and NOTE_COUNT" in loop
        gates = _read(docs["submission_gates"])
        assert "submission-receipt-get" in gates
        assert "--after-note-count {NOTE_COUNT}" in gates

    def test_rescue_commit_blocks_review(self, docs):
        gates = _read(docs["submission_gates"])
        assert "A rescue commit stays a blocker" in gates
        assert gates.index("A rescue commit stays a blocker") < gates.index(
            "review-seed"
        )

    def test_cleanup_report_never_stages_generated_view(self, docs):
        text = _read(docs["cleanup_report"])
        assert "never stage `.yoke/BOARD.md`" in text
        assert "clean -fdX" not in text

    def test_dispatch_context_requires_submission_checks_block(self, docs):
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "submission-receipt-get" in text

    def test_engineer_deterministic_submission_trigger(self, docs):
        """Engineer defines a concrete numeric cutoff.

        Cutoff value is pinned to the agent's current turn budget (300 → 30
        remaining = 10% submission window). If the budget changes, update
        both the agent prose and this assertion in the same commit.
        """
        text = _read(docs["engineer"])
        assert "30 or fewer turns remaining" in text

    def test_engineer_submission_mode_protocol(self, docs):
        """Submission mode defined as finish-the-current-branch-state."""
        text = _read(docs["engineer"])
        assert "Submission Mode Protocol" in text
        assert "Forbidden in submission mode" in text

    def test_engineer_evidence_based_checklist(self, docs):
        """Checks 1-2 are evidence-based, checks 3-4 mandatory."""
        text = _read(docs["engineer"])
        assert "evidence-based" in text.lower()
        assert "Mandatory final-pass check" in text

    def test_engineer_no_advisory_self_check(self, docs):
        """Old advisory 'Self-check' and 'Last 10%' wording removed."""
        text = _read(docs["engineer"])
        assert "Self-check:" not in text
        assert "Last 10% of turns:" not in text

    def test_dispatch_context_submit_only_remediation(self, docs):
        """Conduct defines submit-only remediation at the same attempt."""
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "bounded submission-only remediation" in text
        assert "SAME attempt" in text

    def test_dispatch_context_remediation_bounded(self, docs):
        """Remediation bounded to 20 turns."""
        text = _read_dispatch_context(docs["dispatch_context"])
        assert "max 20 turns" in text
