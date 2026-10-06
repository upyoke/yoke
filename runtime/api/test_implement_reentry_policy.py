"""Tests for implement re-entry and single-lane policy surfaces."""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
IMPLEMENT_REENTRY_MD = SKILL_ROOT / "implement" / "reentry.md"
TESTER_TEMPLATE_MD = SKILL_ROOT / "shared" / "tester-dispatch-template.md"


class TestImplementSkillReentry:
    """Implement re-entry follows the worktree policy selected by the item pin."""

    def _read(self) -> str:
        return IMPLEMENT_REENTRY_MD.read_text()

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
            "implement/reentry.md is missing the CONTRACT ERROR guard for "
            "multi-lane worktree policies"
        )

    def test_multi_lane_redirects_through_the_pinned_binding(self):
        """Multi-lane re-entry names the binding's skill, not a remembered one."""
        text = self._read()
        assert "Run the skill its pinned binding names for that stage." in text
        assert "/yoke conduct" not in text


class TestLanePolicySurfaces:
    """Single-lane surfaces are guarded by the pinned worktree policy."""

    def test_tester_template_lane_convention_documented(self):
        """The Tester template distinguishes item-level and task lanes."""
        text = TESTER_TEMPLATE_MD.read_text()
        assert "single_implementation_lane" in text
        assert "For generated tasks" in text
        assert "task's own worktree branch" in text
