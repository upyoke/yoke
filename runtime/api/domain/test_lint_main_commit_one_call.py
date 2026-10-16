"""One-call ``git add && git commit`` regression coverage.

Sibling of ``test_lint_main_commit.py`` (350-line cap). The client observes
its checkout and ships the effective staged set (currently staged plus the
call's own add targets) as a fact; the policy reads only that fact.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_main_commit
from yoke_harness.hooks import main_commit_client
from runtime.api.domain.test_lint_main_commit import TEST_ITEM_REF, _payload


def _evaluate(command: str, *, staged: list[str], status: list[str] | None = None):
    """Collect the client facts for *command*, then run the policy on them."""
    payload = _payload(command)
    with (
        mock.patch.object(main_commit_client, "_branch", return_value="main"),
        mock.patch.object(main_commit_client, "_staged", return_value=staged),
        mock.patch.object(
            main_commit_client, "_modified_and_untracked", return_value=status
        ),
    ):
        payload.update(main_commit_client.collect_git_commit_facts(payload))
    with mock.patch.object(
        lint_main_commit,
        "_active_worktree_items",
        return_value=[f"{TEST_ITEM_REF}|Some item"],
    ):
        return lint_main_commit.evaluate_payload(payload)


class TestOneCallAddCommit(unittest.TestCase):
    """A single Bash call ``git add X && git commit`` must evaluate the union
    of (currently staged ∪ add targets) — the pre-add index alone made every
    staged-set rule blind to it."""

    def test_one_call_add_commit_blocks_via_add_targets(self) -> None:
        reason = _evaluate(
            "git add runtime/api/domain/foo.py && git commit -m 'wip'", staged=[]
        )
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("runtime/api/domain/foo.py", reason)

    def test_one_call_indeterminate_add_widens_to_status(self) -> None:
        reason = _evaluate(
            "git add -A && git commit -m 'wip'",
            staged=[],
            status=["runtime/api/domain/foo.py"],
        )
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("runtime/api/domain/foo.py", reason)

    def test_one_call_bookkeeping_add_still_allows(self) -> None:
        self.assertIsNone(
            _evaluate("git add AGENTS.md && git commit -m 'docs'", staged=[])
        )
