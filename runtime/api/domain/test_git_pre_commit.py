"""Tests for yoke_core.domain.git_pre_commit."""

from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

from yoke_core.domain import git_pre_commit as mod


# --- Fixture helpers (mirror test_file_line_check.py style) -------------


def _init_git_repo(tmp: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.name", "test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp), "config", "commit.gpgsign", "false"],
        check=True,
    )


def _commit_file(
    tmp: pathlib.Path, relpath: str, contents: str, *, message: str = "c"
) -> None:
    path = tmp / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "add", relpath], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "commit", "-q", "-m", message], check=True
    )


def _stage_file(tmp: pathlib.Path, relpath: str, contents: str) -> None:
    path = tmp / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "add", relpath], check=True)


def _make_lines(n: int, *, tag: str = "x") -> str:
    return "\n".join(f"{tag}{i}" for i in range(n)) + "\n"


def _run_with_cwd(repo: pathlib.Path, stderr_buf: io.StringIO) -> int:
    """Invoke ``mod.run()`` with cwd inside *repo*, capturing stderr."""
    old_cwd = pathlib.Path.cwd()
    try:
        import os

        os.chdir(repo)
        with mock.patch.object(mod.sys, "stderr", stderr_buf):
            return mod.run()
    finally:
        import os

        os.chdir(old_cwd)


# --- Pure-function tests (preserved from the advisory-only hook) --------


class TestFindDiverged(unittest.TestCase):
    def test_intersection(self) -> None:
        self.assertEqual(
            mod.find_diverged(
                ["a.py", "b.py", "c.py"],
                ["b.py", "c.py", "d.py"],
            ),
            ["b.py", "c.py"],
        )

    def test_no_overlap(self) -> None:
        self.assertEqual(
            mod.find_diverged(["a.py"], ["b.py"]),
            [],
        )


class TestFormatWarning(unittest.TestCase):
    def test_contains_paths_and_hint(self) -> None:
        text = mod._format_warning(["foo.py", "bar.py"])
        self.assertIn("foo.py", text)
        self.assertIn("bar.py", text)
        self.assertIn("git add", text)
        self.assertIn("--no-verify", text)


# --- Diverged-files warning still fires & is non-blocking -


class TestDivergedWarningStillAdvisory(unittest.TestCase):
    def _run_with_patched_helpers(
        self,
        diverged: list[str],
        staged: list[str],
        file_line_rc: int,
    ) -> tuple[int, str]:
        sequence = iter([diverged, staged])

        def side_effect(_args):
            return next(sequence)

        buf = io.StringIO()
        with mock.patch.object(mod, "_git_name_only", side_effect=side_effect), \
             mock.patch.object(
                 mod, "_run_file_line_check_or_block", return_value=file_line_rc
             ), \
             mock.patch.object(
                 mod, "_run_worktree_status_check_or_block", return_value=0
             ), \
             mock.patch.object(
                 mod, "_run_path_claim_coverage_check_or_block", return_value=0
             ), \
             mock.patch.object(mod.sys, "stderr", buf):
            rc = mod.run()
        return rc, buf.getvalue()

    def test_no_diverged_still_runs_file_line_check(self) -> None:
        rc, out = self._run_with_patched_helpers([], [], file_line_rc=0)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_overlap_prints_warning_and_file_line_rc_wins(self) -> None:
        rc, out = self._run_with_patched_helpers(
            ["foo.py", "bar.py"], ["foo.py", "baz.py"], file_line_rc=0
        )
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", out)
        self.assertIn("foo.py", out)

    def test_warning_prints_even_when_file_line_hard_fails(self) -> None:
        rc, out = self._run_with_patched_helpers(
            ["foo.py"], ["foo.py"], file_line_rc=1
        )
        self.assertEqual(rc, 1)
        self.assertIn("WARNING", out)


# --- Fixture-based run() tests


class TestRunAgainstFixtureRepo(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name)
        _init_git_repo(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_run_hard_fails_on_oversized_changed_file(self) -> None:
        # AC-1 + AC-7: a newly staged 412-line authored file must hard-fail.
        _commit_file(self.repo, "README.md", "seed\n", message="seed")
        _stage_file(self.repo, "pkg/big.py", _make_lines(412))
        buf = io.StringIO()
        rc = _run_with_cwd(self.repo, buf)
        self.assertEqual(rc, 1)
        err = buf.getvalue()
        self.assertIn("ERROR", err)
        self.assertIn("pkg/big.py", err)
        self.assertIn("--no-verify", err)

    def test_run_passes_on_clean_changes(self) -> None:
        # AC-2 + AC-8: a small staged change passes.
        _commit_file(self.repo, "README.md", "seed\n", message="seed")
        _stage_file(self.repo, "pkg/small.py", "x = 1\n")
        buf = io.StringIO()
        rc = _run_with_cwd(self.repo, buf)
        self.assertEqual(rc, 0)

    def test_run_passes_when_only_temporary_exception_grows(self) -> None:
        # Growth in a TEMPORARY_EXCEPTION path warns only; rc=0.
        _commit_file(
            self.repo, ".yoke/file-line-exceptions",
            "data/fixtures/*.md\n", message="exceptions",
        )
        _commit_file(
            self.repo, "data/fixtures/corpus.md", _make_lines(200), message="seed"
        )
        _stage_file(self.repo, "data/fixtures/corpus.md", _make_lines(500))
        buf = io.StringIO()
        rc = _run_with_cwd(self.repo, buf)
        self.assertEqual(rc, 0)

    def test_run_falls_back_to_empty_tree_on_initial_commit(self) -> None:
        # AC-4 + AC-10: no HEAD yet, stage one small file — must not crash.
        _stage_file(self.repo, "pkg/small.py", "x = 1\n")
        buf = io.StringIO()
        rc = _run_with_cwd(self.repo, buf)
        self.assertEqual(rc, 0)


# --- Fail-closed branch & wiring -------------------------


class TestFailClosedOnMissingChecker(unittest.TestCase):
    def test_pre_commit_blocks_when_checker_module_missing(self) -> None:
        # Force `from yoke_core.domain import file_line_check`
        # to raise ImportError by intercepting __import__ and asserting
        # fail-closed behaviour. This locks in the GAP #2 fix.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "yoke_core.domain" and fromlist and "file_line_check" in fromlist:
                raise ImportError("simulated: file_line_check unavailable")
            return real_import(name, globals, locals, fromlist, level)

        buf = io.StringIO()
        with mock.patch.object(builtins, "__import__", side_effect=fake_import), \
             mock.patch.object(mod.sys, "stderr", buf):
            rc = mod._run_file_line_check_or_block()
        self.assertEqual(rc, 1)
        err = buf.getvalue()
        self.assertIn("checker module not available", err)
        self.assertIn("--no-verify", err)


class TestRunCallsChangedFilesCheckWithStagedTrue(unittest.TestCase):
    def test_run_calls_changed_files_check_with_staged_true(self) -> None:
        # Locks in the GAP #1 fix — the wiring must use staged=True.
        from yoke_core.domain import file_line_check as flc

        captured: dict[str, object] = {}

        def fake_check(**kwargs):
            captured.update(kwargs)
            return flc.CheckVerdict(
                ok=True, hard_fails=[], warnings=[], summary="ok"
            )

        buf = io.StringIO()
        with mock.patch.object(flc, "changed_files_check", side_effect=fake_check), \
             mock.patch.object(mod, "_resolve_repo_root", return_value="/tmp/x"), \
             mock.patch.object(mod.sys, "stderr", buf):
            rc = mod._run_file_line_check_or_block()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.get("staged"), True)
        self.assertEqual(captured.get("repo_root"), pathlib.Path("/tmp/x"))


# --- _format_file_line_summary rendering -------------------------------


class TestFormatFileLineSummary(unittest.TestCase):
    def test_new_file_over_limit(self) -> None:
        from yoke_core.domain import file_line_check as flc
        from yoke_core.domain.file_line_check_helpers import (
            ChangedFile,
            CheckVerdict,
            Classification,
        )

        change = ChangedFile(
            path="runtime/foo.py",
            classification=Classification.AUTHORED,
            old_line_count=0,
            new_line_count=412,
            delta=412,
        )
        verdict = CheckVerdict(
            ok=False, hard_fails=[change], warnings=[], summary="1 hard-fail"
        )
        text = mod._format_file_line_summary(verdict, limit=flc.LIMIT)
        self.assertIn("runtime/foo.py", text)
        self.assertIn("NEW authored file is 412 lines", text)
        self.assertIn("--no-verify", text)
        self.assertIn("file-line-limit gate blocked", text)


if __name__ == "__main__":
    unittest.main()
