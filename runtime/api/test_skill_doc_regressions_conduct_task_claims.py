"""Conduct per-task claim documentation regressions."""

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
)


class TestConductPerTaskClaims:
    CONDUCT = SKILLS / "conduct"

    def test_loop_acquires_per_task_claim_for_each_role(self):
        text = _read(self.CONDUCT / "engineer-tester-loop.md")
        for reason in ("engineer dispatch", "tester dispatch"):
            assert (
                "yoke claims work acquire --epic PREFIX-N --task-num {task_num} "
                f'--reason "{reason}"'
            ) in text, reason

    def test_closeout_releases_per_task_claim(self):
        text = _read(self.CONDUCT / "engineer-tester-closeout.md")
        assert (
            "yoke claims work release --epic PREFIX-N --task-num {task_num} "
            '--reason "tester return"'
        ) in text
        assert "harness_sessions who-claims" not in text
        assert "yoke claims work holder-get" not in text

    def test_no_item_level_sibling_worktree_regression(self):
        # Per-task replacement, not item-level sibling inheritance.
        for fname in ("engineer-tester-closeout.md", "engineer-tester-loop.md"):
            text = _read(self.CONDUCT / fname).lower()
            assert "sibling task worktree" not in text, (
                f"{fname} references 'sibling task worktree'"
            )
