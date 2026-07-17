"""Tests for yoke_core.domain.lint_destructive_git (typed evaluate)."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_destructive_git as ldg
from runtime.harness.hook_runner.types import Next, Outcome


def _payload(command: str, **extra) -> dict:
    p = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    p.update(extra)
    return p


def _record_for(payload: dict) -> "ldg.HookContext":
    """Build the HookContext shape the entry-point's CLI helper would build."""
    return ldg._build_context_from_payload(payload)


def _git_run(repo: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    return subprocess.run(["git", "-C", repo, *args],
        capture_output=True, text=True, check=False, env=env, timeout=10)


def _make_repo(initial_files: dict[str, str] | None = None) -> str:
    repo = tempfile.mkdtemp(prefix="ldg-test-")
    _git_run(repo, "init", "--initial-branch=main")
    _git_run(repo, "config", "user.email", "t@x")
    _git_run(repo, "config", "user.name", "t")
    if initial_files:
        for rel, content in initial_files.items():
            full = pathlib.Path(repo) / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
        _git_run(repo, "add", "-A")
        _git_run(repo, "commit", "-m", "init")
    return repo


def _modify(repo: str, rel: str, content: str) -> None:
    full = pathlib.Path(repo) / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


class TestParseGitInvocations(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(ldg._parse_git_invocations("git reset --hard HEAD~1"),
            [(["reset", "--hard", "HEAD~1"], "")])

    def test_dash_C(self):
        self.assertEqual(ldg._parse_git_invocations("git -C /tmp/x reset --hard"),
            [(["reset", "--hard"], "/tmp/x")])

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
        self.assertEqual(ldg._parse_git_invocations("FOO=bar git reset --hard"),
            [(["reset", "--hard"], "")])

    def test_non_git(self):
        self.assertEqual(ldg._parse_git_invocations("ls -la"), [])


class TestClassifyShape(unittest.TestCase):
    def test_reset_hard(self):
        self.assertEqual(ldg._classify_shape(["reset", "--hard"]), "reset_hard")

    def test_reset_soft(self):
        self.assertIsNone(ldg._classify_shape(["reset", "--soft", "HEAD~1"]))

    def test_reset_mixed_default(self):
        self.assertIsNone(ldg._classify_shape(["reset", "HEAD"]))

    def test_clean_force(self):
        self.assertEqual(ldg._classify_shape(["clean", "-f"]), "clean_force")
        self.assertEqual(ldg._classify_shape(["clean", "-fd"]), "clean_force")
        self.assertEqual(ldg._classify_shape(["clean", "-fdx"]), "clean_force")
        self.assertEqual(ldg._classify_shape(["clean", "--force"]), "clean_force")

    def test_clean_dry_run(self):
        self.assertIsNone(ldg._classify_shape(["clean", "-n"]))
        self.assertIsNone(ldg._classify_shape(["clean", "-nf"]))

    def test_stash_drop_clear(self):
        self.assertEqual(ldg._classify_shape(["stash", "drop"]), "stash_drop")
        self.assertEqual(ldg._classify_shape(["stash", "clear"]), "stash_clear")

    def test_stash_safe(self):
        self.assertIsNone(ldg._classify_shape(["stash"]))
        self.assertIsNone(ldg._classify_shape(["stash", "push", "-u"]))
        self.assertIsNone(ldg._classify_shape(["stash", "list"]))
        self.assertIsNone(ldg._classify_shape(["stash", "pop"]))

    def test_checkout_path_form(self):
        self.assertEqual(ldg._classify_shape(["checkout", "--", "foo.txt"]), "checkout_path_discard")

    def test_checkout_force_branch(self):
        self.assertEqual(ldg._classify_shape(["checkout", "-f", "main"]), "checkout_force_branch")

    def test_checkout_clean_branch(self):
        self.assertIsNone(ldg._classify_shape(["checkout", "main"]))

    def test_checkout_dot_pathspec(self):
        self.assertEqual(ldg._classify_shape(["checkout", "."]), "checkout_path_discard")
        self.assertEqual(ldg._classify_shape(["checkout", "HEAD", "."]), "checkout_path_discard")
        self.assertEqual(ldg._classify_shape(["checkout", "./sub/"]), "checkout_path_discard")

    def test_restore_worktree(self):
        self.assertEqual(ldg._classify_shape(["restore", "--worktree", "foo.txt"]), "restore_worktree_path")
        self.assertEqual(ldg._classify_shape(["restore", "foo.txt"]), "restore_worktree_path")

    def test_restore_staged_only(self):
        self.assertIsNone(ldg._classify_shape(["restore", "--staged", "foo.txt"]))
        self.assertIsNone(ldg._classify_shape(["restore", "-S", "foo.txt"]))

    def test_restore_staged_and_worktree(self):
        self.assertEqual(
            ldg._classify_shape(["restore", "-S", "-W", "foo.txt"]),
            "restore_worktree_path",
        )

    def test_worktree_remove(self):
        self.assertEqual(
            ldg._classify_shape(["worktree", "remove", ".worktrees/a"]),
            "worktree_remove",
        )


class TestPathArgs(unittest.TestCase):
    def test_staged_short_flag_takes_no_value(self):
        self.assertEqual(ldg._path_args(["restore", "-S", "a.txt"]), ["a.txt"])

    def test_source_flags_consume_value(self):
        self.assertEqual(
            ldg._path_args(["restore", "-s", "HEAD~1", "a.txt"]), ["a.txt"])
        self.assertEqual(
            ldg._path_args(["restore", "--source", "HEAD~1", "a.txt"]), ["a.txt"])


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
        with mock.patch.object(ldg, "_read_mode", return_value="deny"), \
             mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]):
            return ldg.evaluate_payload(_payload(command))

    def _eval_with_payload(self, payload: dict) -> tuple[str, str, str] | None:
        with mock.patch.object(ldg, "_read_mode", return_value="deny"), \
             mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]):
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
        for cmd in (f"git -C {repo} clean -f", f"git -C {repo} clean -fd",
                f"git -C {repo} clean -fdx"):
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

        with mock.patch.object(ldg, "_read_mode", return_value="deny"), \
             mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[threat]):
            result = ldg.evaluate_payload(
                _payload("rm -rf .worktrees/cleanup-test", cwd=repo)
            )

        self.assertIsNotNone(result)
        self.assertIn("active claim", result[1])


class TestModePinAndSuppression(unittest.TestCase):
    """Mode-pin verdict + AC-T3 suppression-token audit-only semantics."""

    def setUp(self):
        self.repo = _make_repo(initial_files={"a.txt": "v1\n"})
        _modify(self.repo, "a.txt", "v2\n")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_AC8_token_records_attempt_still_denies(self):
        cmd = f"git -C {self.repo} reset --hard HEAD~1  # lint:no-uncommitted-wipe-check"
        with mock.patch.object(ldg, "_read_mode", return_value="deny"):
            result = ldg.evaluate_payload(_payload(cmd))
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(outcome, "suppression_attempted")
        self.assertEqual(mode, "deny")
        self.assertIn("does NOT unblock", reason)

    def test_AC8_evaluate_token_still_denies_with_attempted_outcome(self):
        # AC-T3: suppression-token is audit-only; evaluate(record) still denies.
        cmd = f"git -C {self.repo} reset --hard HEAD~1  # lint:no-uncommitted-wipe-check"
        with mock.patch.object(ldg, "_read_mode", return_value="deny"), \
             mock.patch.object(ldg, "_emit_audit_event") as emit_mock:
            decision = ldg.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        # outcome arg is the 4th positional (payload, reason, mode, outcome).
        self.assertEqual(emit_mock.call_args.args[3], "suppression_attempted")

    def test_AC9_warn_mode_returns_warn_no_deny_envelope(self):
        with mock.patch.object(ldg, "_read_mode", return_value="warn"), \
             mock.patch.object(ldg, "_emit_audit_event"):
            decision = ldg.evaluate(_record_for(
                _payload(f"git -C {self.repo} reset --hard HEAD~1")))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)

    def test_AC9_deny_mode_emits_envelope(self):
        with mock.patch.object(ldg, "_read_mode", return_value="deny"), \
             mock.patch.object(ldg, "_emit_audit_event"):
            decision = ldg.evaluate(_record_for(
                _payload(f"git -C {self.repo} reset --hard HEAD~1")))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("BLOCKED", envelope["hookSpecificOutput"]["permissionDecisionReason"])


class TestFailOpen(unittest.TestCase):
    def test_invalid_payload_returns_noop(self):
        decision = ldg.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertFalse(decision.block)

    def test_non_bash_tool_no_deny(self):
        result = ldg.evaluate_payload({"tool_name": "Read",
            "tool_input": {"command": "git reset --hard"}})
        self.assertIsNone(result)

    def test_non_git_repo_no_deny(self):
        d = tempfile.mkdtemp(prefix="ldg-non-git-")
        try:
            result = ldg.evaluate_payload(_payload(f"git -C {d} reset --hard HEAD~1"))
            self.assertIsNone(result)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
