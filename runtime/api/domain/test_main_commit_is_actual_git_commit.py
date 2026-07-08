"""Tests for the ``is_actual_git_commit`` classifier.

The tokenizer-based replacement for the legacy ``"git commit" in command``
substring check the main-commit lint uses to decide whether a Bash command
is a real ``git commit`` invocation. Quoted field-note evidence that merely
mentions the words MUST NOT classify as a commit attempt.
"""

from __future__ import annotations

import unittest

from yoke_contracts.hook_runner.main_commit import is_actual_git_commit


class TestIsActualGitCommit(unittest.TestCase):
    def test_bare_commit_command(self) -> None:
        self.assertTrue(is_actual_git_commit('git commit -m "msg"'))

    def test_commit_with_repo_path(self) -> None:
        self.assertTrue(
            is_actual_git_commit('git -C /tmp/repo commit -m "msg"')
        )

    def test_commit_with_config_override(self) -> None:
        self.assertTrue(
            is_actual_git_commit('git -c user.name=Test commit -m "msg"')
        )

    def test_commit_after_separator(self) -> None:
        self.assertTrue(
            is_actual_git_commit('git add -A && git commit -m "msg"')
        )

    def test_commit_inside_double_quoted_argument(self) -> None:
        # The text "git commit" appears inside an --evidence argument as
        # field-note payload -- not a real commit attempt.
        cmd = (
            'yoke ouroboros field-note append --kind failed '
            '--evidence "git commit was blocked by lint-main-commit"'
        )
        self.assertFalse(is_actual_git_commit(cmd))

    def test_commit_inside_single_quoted_argument(self) -> None:
        cmd = (
            "yoke ouroboros field-note append --kind unclear "
            "--evidence 'previous attempt: git commit refused'"
        )
        self.assertFalse(is_actual_git_commit(cmd))

    def test_commit_inside_heredoc_like_payload(self) -> None:
        # printf with a quoted string that mentions the words is not an
        # actual commit invocation.
        cmd = "printf '%s\\n' 'tried git commit and got refused'"
        self.assertFalse(is_actual_git_commit(cmd))

    def test_not_git_at_all(self) -> None:
        self.assertFalse(is_actual_git_commit("ls -la"))

    def test_git_subcommand_other_than_commit(self) -> None:
        self.assertFalse(is_actual_git_commit("git status"))
        self.assertFalse(is_actual_git_commit('git log -1'))

    def test_empty_command(self) -> None:
        self.assertFalse(is_actual_git_commit(""))

    def test_none_command(self) -> None:
        self.assertFalse(is_actual_git_commit(None))  # type: ignore[arg-type]

    def test_unbalanced_quotes_falls_back_to_word_check(self) -> None:
        # Unbalanced quotes prevent shlex tokenization; the helper falls
        # back to the conservative whitespace check. ``git commit`` as
        # adjacent unquoted words is the positive shape there.
        self.assertTrue(is_actual_git_commit('git commit -m "unclosed'))
        self.assertFalse(is_actual_git_commit('"git commit'))


if __name__ == "__main__":
    unittest.main()
