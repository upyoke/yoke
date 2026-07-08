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
