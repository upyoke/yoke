"""Conduct per-task claim documentation regressions."""

from runtime.api.skill_doc_regressions_test_helpers import (
    SKILLS,
    _read,
)


# TestConductPerTaskClaims — per-task epic_task wiring


class TestConductPerTaskClaims:
    CONDUCT = SKILLS / "conduct"

    def test_dispatch_acquires_per_task_claim(self):
        text = _read(self.CONDUCT / "engineer-tester-dispatch.md")
        for needle in (
            "yoke claims work acquire",
            "--epic-id",
            "--task-num",
            "engineer dispatch",
            "target_kind='epic_task'",
            "HALT: engineer dispatch",
            "HALT: tester dispatch",
        ):
            assert needle in text, f"dispatch.md missing: {needle}"

    def test_closeout_releases_per_task_claim(self):
        text = _read(self.CONDUCT / "engineer-tester-closeout.md")
        for needle in (
            "yoke claims work release",
            "--epic-id",
            "--task-num",
            "tester return",
            "yoke claims work holder-list",
            "--session-id-filter",
            "--json",
            "target_kind=epic_task",
            "never touches the parent",
        ):
            assert needle in text.lower() or needle in text, (
                f"closeout.md missing: {needle}"
            )
        assert "harness_sessions who-claims" not in text
        assert "yoke claims work holder-get" not in text

    def test_loop_teaches_per_task_reentry_semantics(self):
        text = _read(self.CONDUCT / "engineer-tester-loop.md")
        for needle in (
            "Per-task work-claim re-entry semantics",
            "Same-session re-acquire",
            "Other-session-held",
            "Stale-by-absent-session",
            "chain_head_freshness",
            "claim_conflict",
        ):
            assert needle in text, f"loop.md missing: {needle}"

    def test_no_item_level_sibling_worktree_regression(self):
        # Per-task replacement, not item-level sibling inheritance.
        for fname in (
            "engineer-tester-dispatch.md",
            "engineer-tester-closeout.md",
            "engineer-tester-loop.md",
        ):
            text = _read(self.CONDUCT / fname).lower()
            assert "sibling task worktree" not in text, (
                f"{fname} references 'sibling task worktree'"
            )
