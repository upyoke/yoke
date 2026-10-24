"""Tests for yoke_core.domain.lint_destructive_git (typed evaluate)."""

from __future__ import annotations


import pathlib
import shutil
import unittest
from unittest import mock

from yoke_core.domain import lint_destructive_git as ldg


from runtime.api.domain.destructive_git_test_helpers import (
    _payload,
    _git_run,
    _make_repo,
    _modify,
)


class TestParseGitInvocations(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            ldg._parse_git_invocations("git reset --hard HEAD~1"),
            [(["reset", "--hard", "HEAD~1"], "")],
        )

    def test_dash_C(self):
        self.assertEqual(
            ldg._parse_git_invocations("git -C /tmp/x reset --hard"),
            [(["reset", "--hard"], "/tmp/x")],
        )

    def test_chained(self):
        out = ldg._parse_git_invocations("git status && git reset --hard")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1][0][0], "reset")

    def test_newline_separated(self):
        out = ldg._parse_git_invocations("echo x\ngit reset --hard")
        self.assertEqual(out, [(["reset", "--hard"], "")])

    def test_newline_separated_multiple_git(self):
        out = ldg._parse_git_invocations("git status\ngit stash drop")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1][0], ["stash", "drop"])

    def test_env_prefix(self):
        self.assertEqual(
            ldg._parse_git_invocations("FOO=bar git reset --hard"),
            [(["reset", "--hard"], "")],
        )

    def test_non_git(self):
        self.assertEqual(ldg._parse_git_invocations("ls -la"), [])


class TestEvaluatePayload(unittest.TestCase):
    """End-to-end verdict tests with real temp git repos."""

    def setUp(self):
        self.repos: list[str] = []

    def tearDown(self):
        for r in self.repos:
            shutil.rmtree(r, ignore_errors=True)

    def _repo(self, **kw) -> str:
        r = _make_repo(**kw)
        self.repos.append(r)
        return r

    def _dirty(self) -> str:
        """Repo with a.txt tracked + modified (the common dirty-state shape)."""
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        _modify(repo, "a.txt", "v2\n")
        return repo

    def _eval(self, command: str) -> tuple[str, str, str] | None:
        # Force deny mode regardless of project config (tests stay deterministic).
        with (
            mock.patch.object(ldg, "_read_mode", return_value="deny"),
            mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]),
        ):
            return ldg.evaluate_payload(_payload(command))

    def _eval_with_payload(self, payload: dict) -> tuple[str, str, str] | None:
        with (
            mock.patch.object(ldg, "_read_mode", return_value="deny"),
            mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]),
        ):
            return ldg.evaluate_payload(payload)

    def _linked_worktree(self, repo: str, branch: str = "cleanup-test") -> str:
        wt = str(pathlib.Path(repo) / ".worktrees" / branch)
        _git_run(repo, "worktree", "add", wt, "-b", branch, "main")
        return wt

    def test_AC2_reset_hard_with_modified_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} reset --hard HEAD~1")
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("a.txt", reason)
        self.assertIn("git stash", reason)

    def test_AC2_reset_hard_clean_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        self.assertIsNone(self._eval(f"git -C {repo} reset --hard HEAD"))

    def test_AC3_checkout_path_modified_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} checkout -- a.txt")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("a.txt", result[1])

    def test_AC3_checkout_path_unmodified_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n", "b.txt": "v1\n"})
        _modify(repo, "a.txt", "v2\n")
        # b.txt is unmodified — checkout of b.txt should allow
        self.assertIsNone(self._eval(f"git -C {repo} checkout -- b.txt"))

    def test_newline_separated_reset_hard_blocks(self):
        repo = self._dirty()
        result = self._eval(f"echo preparing\ngit -C {repo} reset --hard HEAD~1")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("a.txt", result[1])

    def test_checkout_dot_modified_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} checkout .")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("a.txt", result[1])

    def test_checkout_ref_then_dot_modified_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} checkout HEAD .")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_checkout_existing_path_modified_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} checkout a.txt")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("a.txt", result[1])

    def test_checkout_branch_name_dirty_allows(self):
        repo = self._dirty()
        self.assertIsNone(self._eval(f"git -C {repo} checkout main"))

    def test_AC3_restore_worktree_modified_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} restore --worktree a.txt")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_AC3_restore_worktree_unmodified_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        self.assertIsNone(self._eval(f"git -C {repo} restore --worktree a.txt"))

    def test_checkout_force_branch_blocks_only_when_dirty(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        self.assertIsNone(self._eval(f"git -C {repo} checkout -f main"))
        _modify(repo, "a.txt", "v2\n")
        result = self._eval(f"git -C {repo} checkout -f main")
        self.assertIn("a.txt", result[1])

    def test_AC4_clean_force_with_untracked_blocks(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        _modify(repo, "junk.tmp", "x")  # untracked
        for cmd in (
            f"git -C {repo} clean -f",
            f"git -C {repo} clean -fd",
            f"git -C {repo} clean -fdx",
        ):
            result = self._eval(cmd)
            self.assertIsNotNone(result, f"clean variant should block: {cmd}")
            self.assertIn("junk.tmp", result[1])

    def test_AC4_clean_force_no_untracked_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        self.assertIsNone(self._eval(f"git -C {repo} clean -f"))

    def test_AC4_clean_force_path_scope_ignores_unrelated_untracked(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        _modify(repo, "other/junk.tmp", "x")
        self.assertIsNone(self._eval(f"git -C {repo} clean -f target"))
        _modify(repo, "target/junk.tmp", "x")
        result = self._eval(f"git -C {repo} clean -f target")
        self.assertIn("target/", result[1])
        self.assertNotIn("other/junk.tmp", result[1])

    def test_AC4_clean_force_uses_git_dry_run_scope(self):
        repo = self._repo(initial_files={".gitignore": "ignored.tmp\n"})
        _modify(repo, "dir/junk.tmp", "x")
        self.assertIsNone(self._eval(f"git -C {repo} clean -f"))
        self.assertIsNotNone(self._eval(f"git -C {repo} clean -fd"))
        shutil.rmtree(pathlib.Path(repo) / "dir")
        _modify(repo, "ignored.tmp", "x")
        self.assertIsNone(self._eval(f"git -C {repo} clean -fd"))
        self.assertIsNotNone(self._eval(f"git -C {repo} clean -fdx"))

    def test_AC5_stash_drop_with_stash_blocks(self):
        repo = self._dirty()
        _git_run(repo, "stash", "push", "-m", "wip")
        result = self._eval(f"git -C {repo} stash drop")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("stash", result[1].lower())

    def test_AC5_stash_clear_with_stashes_blocks(self):
        repo = self._dirty()
        _git_run(repo, "stash", "push", "-m", "wip")
        self.assertIsNotNone(self._eval(f"git -C {repo} stash clear"))

    def test_AC5_stash_drop_no_stash_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        self.assertIsNone(self._eval(f"git -C {repo} stash drop"))

    def test_AC6_reset_soft_allows_regardless(self):
        repo = self._dirty()
        self.assertIsNone(self._eval(f"git -C {repo} reset --soft HEAD~1"))

    def test_AC6_reset_mixed_allows_regardless(self):
        repo = self._dirty()
        self.assertIsNone(self._eval(f"git -C {repo} reset HEAD"))
        self.assertIsNone(self._eval(f"git -C {repo} reset --mixed HEAD"))

    def test_AC7_stash_push_allows(self):
        repo = self._dirty()
        self.assertIsNone(self._eval(f"git -C {repo} stash push -u"))
        self.assertIsNone(self._eval(f"git -C {repo} stash"))

    def test_AC7_restore_staged_allows(self):
        repo = self._dirty()
        _git_run(repo, "add", "a.txt")
        self.assertIsNone(self._eval(f"git -C {repo} restore --staged a.txt"))

    def test_restore_staged_short_flag_allows(self):
        repo = self._dirty()
        _git_run(repo, "add", "a.txt")
        self.assertIsNone(self._eval(f"git -C {repo} restore -S a.txt"))

    def test_restore_staged_and_worktree_blocks(self):
        repo = self._dirty()
        result = self._eval(f"git -C {repo} restore -S -W a.txt")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("a.txt", result[1])

    def test_worktree_remove_dirty_linked_worktree_blocks(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        wt = self._linked_worktree(repo)
        _modify(wt, "a.txt", "v2\n")

        result = self._eval(f"git -C {repo} worktree remove {wt}")

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("git worktree remove", result[1])
        self.assertIn("a.txt", result[1])

    def test_worktree_remove_clean_linked_worktree_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        wt = self._linked_worktree(repo)

        self.assertIsNone(self._eval(f"git -C {repo} worktree remove {wt}"))

    def test_rm_rf_worktree_with_ignored_file_blocks(self):
        repo = self._repo(initial_files={".gitignore": "cache/\n", "a.txt": "v1\n"})
        wt = self._linked_worktree(repo)
        pathlib.Path(wt, "cache").mkdir()
        _modify(wt, "cache/evidence.log", "keep\n")

        result = self._eval_with_payload(
            _payload("rm -rf .worktrees/cleanup-test", cwd=repo)
        )

        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("rm -rf .worktrees/<path>", result[1])
        self.assertIn("ignored: cache/evidence.log", result[1])

    def test_rm_rf_clean_worktree_allows(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        self._linked_worktree(repo)

        self.assertIsNone(
            self._eval_with_payload(
                _payload("rm -rf .worktrees/cleanup-test", cwd=repo)
            )
        )

    def test_rm_rf_active_claim_blocks(self):
        repo = self._repo(initial_files={"a.txt": "v1\n"})
        wt = self._linked_worktree(repo)
        threat = f"{wt} active claim session=sess item=42"

        with (
            mock.patch.object(ldg, "_read_mode", return_value="deny"),
            mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[threat]),
        ):
            result = ldg.evaluate_payload(
                _payload("rm -rf .worktrees/cleanup-test", cwd=repo)
            )

        self.assertIsNotNone(result)
        self.assertIn("active claim", result[1])
