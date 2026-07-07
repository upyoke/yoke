"""Tests for advance re-entry and preflight gate fixes."""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
ADVANCE_SKILL_MD = SKILL_ROOT / "advance" / "SKILL.md"
PREFLIGHT_CHECKS_MD = SKILL_ROOT / "advance" / "preflight-checks.md"
FINALIZE_MD = SKILL_ROOT / "advance" / "finalize.md"
PROJECT_E2E_MD = SKILL_ROOT / "advance" / "project-e2e.md"
BROWSER_QA_MD = SKILL_ROOT / "advance" / "browser-qa-checks.md"
PREFLIGHT_RECOVERY_MD = SKILL_ROOT / "advance" / "preflight-recovery.md"
TESTER_TEMPLATE_MD = SKILL_ROOT / "shared" / "tester-dispatch-template.md"


class TestAdvanceSkillReentry:
    """AC-3: advance/SKILL.md uses resolver for re-entry, guards multi-worktree epics."""

    def _read(self) -> str:
        return ADVANCE_SKILL_MD.read_text()

    def test_resolver_used_in_reentry(self):
        """Re-entry must call worktree_item_resolve instead of reading items.worktree directly."""
        text = self._read()
        assert "worktree_item_resolve" in text, (
            "advance/SKILL.md does not use worktree_item_resolve for re-entry"
        )

    def test_multi_worktree_contract_error(self):
        """Re-entry for a multi-worktree epic must emit CONTRACT ERROR and redirect."""
        text = self._read()
        assert "CONTRACT ERROR" in text, (
            "advance/SKILL.md is missing the CONTRACT ERROR guard for multi-worktree epics"
        )

    def test_redirect_to_conduct(self):
        """Multi-worktree epic re-entry must redirect to /yoke conduct."""
        text = self._read()
        assert "/yoke conduct" in text, (
            "advance/SKILL.md does not redirect multi-worktree epics to /yoke conduct"
        )


class TestPreflightChecksGate:
    """AC-4, AC-5, AC-10: Epic Task Completion Gate fires only at implemented/release."""

    def _read(self) -> str:
        return PREFLIGHT_CHECKS_MD.read_text()

    def test_gate_skips_reviewing_implementation(self):
        """Gate skip condition must include reviewing-implementation."""
        text = self._read()
        assert "reviewing-implementation" in text, (
            "preflight-checks.md Epic Task Completion Gate does not skip reviewing-implementation"
        )

    def test_gate_skips_reviewed_implementation(self):
        """Gate skip condition must include reviewed-implementation."""
        text = self._read()
        assert "reviewed-implementation" in text, (
            "preflight-checks.md Epic Task Completion Gate does not skip reviewed-implementation"
        )

    def test_gate_skips_polishing_implementation(self):
        """Gate skip condition must include polishing-implementation."""
        text = self._read()
        assert "polishing-implementation" in text, (
            "preflight-checks.md Epic Task Completion Gate does not skip polishing-implementation"
        )

    def test_gate_fires_at_implemented(self):
        """Gate description must mention implemented as a trigger target."""
        text = self._read()
        # The heading should name implemented as a gating boundary
        assert "`implemented`" in text, (
            "preflight-checks.md Epic Task Completion Gate heading does not name `implemented`"
        )

    def test_gate_fires_at_release(self):
        """Gate description must mention release as a trigger target."""
        text = self._read()
        assert "`release`" in text, (
            "preflight-checks.md Epic Task Completion Gate heading does not name `release`"
        )


class TestAC9Surfaces:
    """AC-9: issue-only surfaces are guarded or documented."""

    def test_finalize_epic_guard(self):
        """finalize.md WORKTREE_PATH fallback must skip for epics."""
        text = FINALIZE_MD.read_text()
        assert "epic" in text, (
            "finalize.md does not guard the WORKTREE_PATH fallback against epic items"
        )

    def test_project_e2e_epic_guard(self):
        """project-e2e.md worktree preference must skip for epics."""
        text = PROJECT_E2E_MD.read_text()
        assert "epic" in text, (
            "project-e2e.md does not guard the worktree path preference against epic items"
        )

    def test_browser_qa_issue_only_documented(self):
        """browser-qa-checks.md must document the issue-only invariant."""
        text = BROWSER_QA_MD.read_text()
        assert "issue" in text.lower(), (
            "browser-qa-checks.md does not document the issue-only invariant"
        )

    def test_preflight_recovery_uses_resolver(self):
        """preflight-recovery.md Merge Verification Gate must use the resolver."""
        text = PREFLIGHT_RECOVERY_MD.read_text()
        assert "worktree_item_resolve" in text, (
            "preflight-recovery.md Merge Verification Gate does not use worktree_item_resolve"
        )

    def test_preflight_recovery_blocks_after_any_unmerged_worktree(self):
        """Merge Verification Gate must preserve the block flag after iterating worktrees."""
        text = PREFLIGHT_RECOVERY_MD.read_text()
        assert "| while IFS= read -r _wt_branch" not in text, (
            "preflight-recovery.md stores the block flag inside a pipeline subshell"
        )
        assert 'if [ "$_mv_block" -ne 0 ]; then' in text, (
            "preflight-recovery.md does not block after detecting an unmerged worktree"
        )
        assert "done <<EOF" in text, (
            "preflight-recovery.md must expand the resolved branch list in the here-doc"
        )

    def test_tester_template_convention_documented(self):
        """tester-dispatch-template.md must document the issue-only convention."""
        text = TESTER_TEMPLATE_MD.read_text()
        assert "issue" in text.lower(), (
            "tester-dispatch-template.md does not document the issue-only convention"
        )
