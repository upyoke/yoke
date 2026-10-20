"""Tests for implement re-entry and single-lane policy surfaces."""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).parents[2] / ".agents" / "skills" / "yoke"
IMPLEMENT_REENTRY_MD = SKILL_ROOT / "implement" / "reentry.md"
IMPLEMENT_ENTRY_MD = SKILL_ROOT / "implement" / "entry.md"
TESTER_TEMPLATE_MD = SKILL_ROOT / "shared" / "tester-dispatch-template.md"


class TestImplementSkillReentry:
    """Implement re-entry follows the worktree policy selected by the item pin."""

    def test_single_lane_reentry_reads_the_active_item_worktree_lane(self):
        """A single implementation lane reads the canonical lane model."""
        text = IMPLEMENT_REENTRY_MD.read_text()
        assert "worktree policy `none`" in text
        assert (
            "yoke item-worktrees get PREFIX-N --lane-role implementation --field path"
            in text
        )
        assert "never compose" in text
        assert "yoke items get {N} worktree" not in text

    def test_non_implement_binding_stops_with_the_bound_skill(self):
        """A binding other than implement reports the bound skill and stops."""
        text = " ".join(IMPLEMENT_ENTRY_MD.read_text().split())
        assert "yoke workflows item get PREFIX-N --json" in text
        assert "must be `implement`" in text
        assert "report the live stage and bound skill and stop" in text
        assert "/yoke conduct" not in IMPLEMENT_REENTRY_MD.read_text()


class TestLanePolicySurfaces:
    """Single-lane surfaces are guarded by the pinned worktree policy."""

    def test_tester_template_lane_convention_documented(self):
        """The Tester template sends a generated task to its own lane."""
        assert "a task uses its own lane" in TESTER_TEMPLATE_MD.read_text()
