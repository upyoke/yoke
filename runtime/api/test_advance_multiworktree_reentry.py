"""Tests for advance re-entry and preflight gate fixes."""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
ADVANCE_SKILL_MD = SKILL_ROOT / "advance" / "SKILL.md"
PREFLIGHT_CHECKS_MD = SKILL_ROOT / "advance" / "preflight-checks.md"
FINALIZE_MD = SKILL_ROOT / "advance" / "finalize.md"
PROJECT_E2E_MD = SKILL_ROOT / "advance" / "project-e2e.md"
PREFLIGHT_RECOVERY_MD = SKILL_ROOT / "advance" / "preflight-recovery.md"
TESTER_TEMPLATE_MD = SKILL_ROOT / "shared" / "tester-dispatch-template.md"


class TestAdvanceSkillReentry:
    """Advance re-entry follows the worktree policy selected by the item pin."""

    def _read(self) -> str:
        return ADVANCE_SKILL_MD.read_text()

    def test_single_lane_reentry_reads_the_active_item_worktree_lane(self):
        """A single implementation lane reads the canonical lane model."""
        text = self._read()
        assert 'if [ "$_worktree_policy" = "single_implementation_lane" ]; then' in text
        assert "_wt_branch=$(yoke item-worktrees get PREFIX-{N}" in text
        assert "--lane-role implementation --field branch" in text
        assert "yoke items get {N} worktree" not in text

    def test_multi_lane_contract_error(self):
        """A multi-lane policy must emit CONTRACT ERROR and redirect."""
        text = self._read()
        assert "CONTRACT ERROR" in text, (
            "advance/SKILL.md is missing the CONTRACT ERROR guard for "
            "multi-lane worktree policies"
        )

    def test_redirect_to_conduct(self):
        """Conduct-owned multi-lane re-entry must redirect to /yoke conduct."""
        text = self._read()
        assert "/yoke conduct" in text, (
            "advance/SKILL.md does not redirect conduct-owned lanes to /yoke conduct"
        )


class TestPreflightChecksGate:
    """The Epic Task Completion Gate fires only at implemented or release."""

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


class TestLanePolicySurfaces:
    """Single-lane surfaces are guarded by the pinned worktree policy."""

    def test_finalize_single_lane_guard(self):
        """The finalize WORKTREE_PATH fallback is single-lane only."""
        text = FINALIZE_MD.read_text()
        assert '[ "$_worktree_policy" = "single_implementation_lane" ]' in text
        assert "_finalize_workflow_id" not in text

    def test_project_e2e_multi_lane_guard(self):
        """Deployed-stack QA delegates a multi-lane policy to conduct."""
        text = PROJECT_E2E_MD.read_text()
        assert "worktrees=worker_and_integration_lanes" in text
        assert "pinned `conduct` skill" in text
        assert "parent item has no single" in text

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

    def test_tester_template_lane_convention_documented(self):
        """The Tester template distinguishes item-level and task lanes."""
        text = TESTER_TEMPLATE_MD.read_text()
        assert "single_implementation_lane" in text
        assert "For generated tasks" in text
        assert "task's own worktree branch" in text
