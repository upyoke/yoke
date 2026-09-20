"""Destructive-git must classify the verb, not the spelling of its argument.

The careful form ``git stash drop "stash@{1}"`` is already refused. The
same drop written with a loop variable was not: the guard never saw a
``git`` invocation, so six live stashes could disappear with no denial
and no audit. These tests pin that bypass closed, require fail-closed
when a named target cannot be resolved, and pin the refusal wording a
caller actually reads.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_destructive_git as ldg
from yoke_core.domain import lint_destructive_git_messages as messages


def _payload(command: str, **extra) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _git_run(repo: str, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )


def _make_repo() -> str:
    repo = tempfile.mkdtemp(prefix="ldg-var-")
    _git_run(repo, "init", "--initial-branch=main")
    _git_run(repo, "config", "user.email", "t@x")
    _git_run(repo, "config", "user.name", "t")
    pathlib.Path(repo, "a.txt").write_text("v1\n")
    _git_run(repo, "add", "-A")
    _git_run(repo, "commit", "-m", "init")
    return repo


def _push_stash(repo: str, marker: str) -> None:
    pathlib.Path(repo, "a.txt").write_text(f"{marker}\n")
    _git_run(repo, "stash", "push", "-u", "-m", marker)


class TestStashDropVariableShape(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _make_repo()
        for marker in ("zero", "one", "two"):
            _push_stash(self.repo, marker)

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)

    def _eval(self, command: str):
        with (
            mock.patch.object(ldg, "_read_mode", return_value="deny"),
            mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]),
        ):
            return ldg.evaluate_payload(_payload(command))

    def test_literal_stash_selector_is_denied(self) -> None:
        result = self._eval(f'git -C {self.repo} stash drop "stash@{{1}}"')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_loop_variable_stash_drop_is_denied(self) -> None:
        command = f'for n in 1; do git -C {self.repo} stash drop "stash@{{$n}}"; done'
        result = self._eval(command)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertEqual(result[2], "denied")

    def test_unresolvable_selector_is_denied(self) -> None:
        result = self._eval(f'git -C {self.repo} stash drop "stash@{{$n}}"')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        reason = result[1]
        self.assertIn("stash@{0}", reason)
        self.assertIn("stash@{1}", reason)
        self.assertIn("stash@{2}", reason)

    def test_named_selector_is_the_only_listed_target(self) -> None:
        result = self._eval(f'git -C {self.repo} stash drop "stash@{{1}}"')
        self.assertIsNotNone(result)
        reason = result[1]
        self.assertIn("stash@{1}", reason)
        self.assertNotIn("stash@{0}", reason)
        self.assertNotIn("stash@{2}", reason)

    def test_stash_refusal_does_not_advise_committing_the_stash(self) -> None:
        result = self._eval(f"git -C {self.repo} stash drop")
        self.assertIsNotNone(result)
        reason = result[1].lower()
        self.assertNotIn("stash or commit work", reason)
        self.assertNotIn("stash/commit", reason)

    def test_suppression_token_says_the_check_cannot_be_suppressed(self) -> None:
        command = f"git -C {self.repo} stash drop  {messages.SUPPRESSION_TOKEN}"
        result = self._eval(command)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn("cannot be suppressed", reason.lower())
        self.assertIn("does NOT unblock", reason)
