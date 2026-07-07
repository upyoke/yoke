"""One-call ``git add && git commit`` regression coverage.

Sibling of ``test_lint_main_commit.py`` (350-line cap).
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_main_commit, lint_staged_union
from runtime.api.domain.test_lint_main_commit import _payload


class TestOneCallAddCommit(unittest.TestCase):
    """Field-note 12940 regression: a single Bash call ``git add X && git
    commit`` must evaluate the union of (currently staged ∪ add targets) —
    the pre-add index alone made every staged-set rule blind to it."""

    def test_one_call_add_commit_blocks_via_add_targets(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(lint_main_commit, "_staged_files", return_value=[]), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["42|Some item"],
            ):
            reason = lint_main_commit.evaluate_payload(
                _payload("git add runtime/api/domain/foo.py && git commit -m 'wip'")
            )
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("runtime/api/domain/foo.py", reason)

    def test_one_call_indeterminate_add_widens_to_status(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(lint_main_commit, "_staged_files", return_value=[]), \
             mock.patch.object(
                lint_staged_union,
                "_modified_and_untracked",
                return_value=["runtime/api/domain/foo.py"],
            ), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["42|Some item"],
            ):
            reason = lint_main_commit.evaluate_payload(
                _payload("git add -A && git commit -m 'wip'")
            )
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("runtime/api/domain/foo.py", reason)

    def test_one_call_bookkeeping_add_still_allows(self) -> None:
        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(lint_main_commit, "_staged_files", return_value=[]), \
             mock.patch.object(
                lint_main_commit,
                "_active_worktree_items",
                return_value=["42|Some item"],
            ):
            self.assertIsNone(
                lint_main_commit.evaluate_payload(
                    _payload("git add AGENTS.md && git commit -m 'docs'")
                )
            )

    def test_one_call_freshness_rule_sees_add_targets(self) -> None:
        # The strategy-freshness deny receives the union AND the add
        # targets marked for worktree-content verification.
        seen: dict = {}

        def fake_denial(
            staged, *, worktree_content_paths=frozenset(), rows_cache=None,
        ):
            seen["staged"] = list(staged)
            seen["worktree"] = set(worktree_content_paths)
            return "BLOCKED: stale strategy rendered view (test)"

        with mock.patch.object(lint_main_commit, "_current_branch", return_value="main"), \
             mock.patch.object(lint_main_commit, "_staged_files", return_value=[]), \
             mock.patch.object(
                lint_main_commit.strategy_freshness,
                "staged_freshness_denial",
                side_effect=fake_denial,
            ):
            reason = lint_main_commit.evaluate_payload(
                _payload("git add .yoke/strategy/MISSION.md && git commit -m 'x'")
            )
        self.assertEqual(reason, "BLOCKED: stale strategy rendered view (test)")
        self.assertEqual(seen["staged"], [".yoke/strategy/MISSION.md"])
        self.assertEqual(seen["worktree"], {".yoke/strategy/MISSION.md"})

from runtime.api.domain.test_lint_main_commit_strategy_freshness import (  # noqa: E402,F401
    EDITED_MISSION,
    FRESH_MISSION,
    MISSION_REL,
    commit_world,
    tmp_db,
)


class TestOneCallWorktreeContentRouting:
    """Add-derived paths verify WORKTREE content: the pending add
    overwrites the index entry, so ``git show :<path>`` would verify
    content the commit does not ship."""

    def test_stale_disk_fresh_index_denies(self, commit_world, monkeypatch):
        # Protection direction: a stale DISK copy riding a fresh-looking
        # index entry must deny — the commit ships the disk copy.
        commit_world.blobs[MISSION_REL] = FRESH_MISSION
        monkeypatch.setattr(
            lint_staged_union, "worktree_blob",
            {MISSION_REL: EDITED_MISSION}.get,
        )
        reason = lint_main_commit.evaluate_payload(
            _payload(f"git add {MISSION_REL} && git commit -m 'x'")
        )
        assert reason is not None
        assert "stale strategy rendered view" in reason

    def test_fresh_disk_stale_index_allows(self, commit_world, monkeypatch):
        # Usability direction: the legit one-call fresh-render commit must
        # not false-deny on the not-yet-overwritten index blob; the
        # matches-the-master authorization also reads the worktree copy.
        commit_world.blobs[MISSION_REL] = EDITED_MISSION
        monkeypatch.setattr(
            lint_staged_union, "worktree_blob",
            {MISSION_REL: FRESH_MISSION}.get,
        )
        reason = lint_main_commit.evaluate_payload(
            _payload(f"git add {MISSION_REL} && git commit -m 'x'")
        )
        assert reason is None
