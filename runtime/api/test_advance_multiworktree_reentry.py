"""Tests for advance re-entry and single-lane policy surfaces."""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
ADVANCE_REENTRY_MD = SKILL_ROOT / "advance" / "reentry.md"
FINALIZE_MD = SKILL_ROOT / "advance" / "finalize.md"
PROJECT_E2E_MD = SKILL_ROOT / "advance" / "project-e2e.md"
TESTER_TEMPLATE_MD = SKILL_ROOT / "shared" / "tester-dispatch-template.md"


class TestAdvanceSkillReentry:
    """Advance re-entry follows the worktree policy selected by the item pin."""

    def _read(self) -> str:
        return ADVANCE_REENTRY_MD.read_text()

    def test_single_lane_reentry_reads_the_active_item_worktree_lane(self):
        """A single implementation lane reads the canonical lane model."""
        text = self._read()
        assert 'if [ "$_worktree_policy" = "single_implementation_lane" ]; then' in text
        assert "_wt_branch=$(yoke item-worktrees get PREFIX-N" in text
        assert "--lane-role implementation --field branch" in text
        assert "yoke items get {N} worktree" not in text

    def test_multi_lane_contract_error(self):
        """A multi-lane policy must emit CONTRACT ERROR and redirect."""
        text = self._read()
        assert "CONTRACT ERROR" in text, (
            "advance/reentry.md is missing the CONTRACT ERROR guard for "
            "multi-lane worktree policies"
        )

    def test_redirect_to_conduct(self):
        """Conduct-owned multi-lane re-entry must redirect to /yoke conduct."""
        text = self._read()
        assert "/yoke conduct" in text, (
            "advance/reentry.md does not redirect conduct-owned lanes to /yoke conduct"
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

    def test_tester_template_lane_convention_documented(self):
        """The Tester template distinguishes item-level and task lanes."""
        text = TESTER_TEMPLATE_MD.read_text()
        assert "single_implementation_lane" in text
        assert "For generated tasks" in text
        assert "task's own worktree branch" in text
