"""Tests for yoke_core.domain.classify_dirty_files."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from yoke_core.domain import classify_dirty_files as mod


class TestPatternMatching(unittest.TestCase):
    def test_flat_file(self) -> None:
        self.assertFalse(mod.is_yoke_managed_pattern("runtime/api/domain/foo.py"))
        self.assertTrue(mod.is_yoke_managed_pattern(".yoke/strategy/PAD.md"))

    def test_projects_tree_is_not_managed(self) -> None:
        self.assertFalse(mod.is_yoke_managed_pattern("projects/externalwebapp/ops.sh"))
        self.assertFalse(
            mod.is_yoke_managed_pattern("projects/foo/bar/baz.txt")
        )

    def test_scripts_tree(self) -> None:
        self.assertTrue(
            mod.is_yoke_managed_pattern(
                ".agents/skills/yoke/scripts/item-db.sh"
            )
        )
        self.assertTrue(
            mod.is_yoke_managed_pattern(
                ".claude/skills/yoke/scripts/item-db.sh"
            )
        )

    def test_simulation_file(self) -> None:
        self.assertTrue(
            mod.is_yoke_managed_pattern(
                "ouroboros/simulation-plan.md"
            )
        )
        self.assertFalse(
            mod.is_yoke_managed_pattern("ouroboros/patterns.md")
        )

    def test_non_managed_paths(self) -> None:
        self.assertFalse(mod.is_yoke_managed_pattern("README.md"))
        self.assertFalse(mod.is_yoke_managed_pattern("src/main.js"))
        self.assertFalse(mod.is_yoke_managed_pattern(".yoke/BOARD.md"))
        self.assertFalse(mod.is_yoke_managed_pattern("data/orphan.md"))


class TestClassifyFile(unittest.TestCase):
    def test_non_backlog_managed_shortcut(self) -> None:
        self.assertEqual(mod.classify_file(".yoke/strategy/PAD.md"), "yoke-managed")
        self.assertEqual(
            mod.classify_file(".agents/skills/yoke/scripts/foo.sh"),
            "yoke-managed",
        )

    def test_non_managed(self) -> None:
        self.assertEqual(mod.classify_file("README.md"), "user-authored")
        self.assertEqual(mod.classify_file("src/main.js"), "user-authored")

    def test_root_data_is_not_managed_pattern(self) -> None:
        # Root data residue is outside the managed pattern list; the
        # local-shape disposition guard owns surfacing it.
        self.assertEqual(mod.classify_file("data/orphan.md"), "user-authored")


class TestExtractBodyAfterFrontmatter(unittest.TestCase):
    def test_extracts_body(self) -> None:
        content = "---\nfoo: 1\n---\n\nHello\nWorld\n"
        self.assertEqual(
            mod._extract_body_after_frontmatter(content),
            "\nHello\nWorld\n",
        )

    def test_no_frontmatter_returns_empty_body(self) -> None:
        # Only the opening delimiter — no closing one — means there is no body.
        self.assertEqual(mod._extract_body_after_frontmatter("just text\n"), "")


class TestClassifyDirtyFiles(unittest.TestCase):
    def _init_repo(self, tmpdir: str) -> None:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(
            ["git", "init", "-q", tmpdir],
            env=env,
            check=True,
            capture_output=True,
        )
        # Initial commit
        with open(os.path.join(tmpdir, "README.md"), "w") as f:
            f.write("initial\n")
        subprocess.run(
            ["git", "-C", tmpdir, "add", "README.md"], env=env, check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", tmpdir, "commit", "-q", "-m", "init"],
            env=env,
            check=True,
            capture_output=True,
        )
        self._env = env

    def test_bulk_classification_mixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self._init_repo(tmpdir)
            # Yoke-managed addition
            os.makedirs(os.path.join(tmpdir, "ouroboros"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "ouroboros", "simulation-YOK-9999.md"), "w",
            ) as f:
                f.write("yoke-managed content\n")
            # User-authored addition
            with open(os.path.join(tmpdir, "src_main.py"), "w") as f:
                f.write("print('hi')\n")
            # Run classify_dirty_files from inside the repo
            cwd_old = os.getcwd()
            os.chdir(tmpdir)
            try:
                yoke_files, user_files = mod.classify_dirty_files()
            finally:
                os.chdir(cwd_old)
        self.assertIn("ouroboros/simulation-YOK-9999.md", yoke_files)
        self.assertIn("src_main.py", user_files)

    def test_bulk_classification_uses_explicit_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as otherdir:
            self._init_repo(tmpdir)
            os.makedirs(os.path.join(tmpdir, "ouroboros"), exist_ok=True)
            with open(
                os.path.join(tmpdir, "ouroboros", "simulation-YOK-9999.md"), "w",
            ) as f:
                f.write("yoke-managed content\n")
            with open(os.path.join(tmpdir, "src_main.py"), "w") as f:
                f.write("print('hi')\n")

            cwd_old = os.getcwd()
            os.chdir(otherdir)
            try:
                yoke_files, user_files = mod.classify_dirty_files(repo_path=tmpdir)
            finally:
                os.chdir(cwd_old)

        self.assertIn("ouroboros/simulation-YOK-9999.md", yoke_files)
        self.assertIn("src_main.py", user_files)

    def test_exclude_worktrees(self) -> None:
        files = [
            "normal.md",
            ".worktrees/YOK-1/foo.md",
            ".claude/worktrees/YOK-2/bar.md",
        ]
        self.assertEqual(
            mod._exclude_worktree_paths(files),
            ["normal.md"],
        )


class TestCli(unittest.TestCase):
    def test_patterns_command(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mod.main(["patterns"])
        self.assertEqual(rc, 0)
        out = buf.getvalue().strip()
        self.assertIn(".yoke/strategy/PAD.md", out)
        self.assertIn("ouroboros/simulation-*.md", out)
        self.assertNotIn("data/orphan.md", out)

    def test_classify_file_command(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = mod.main(["classify-file", ".yoke/strategy/PAD.md"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "yoke-managed")

    def test_is_managed_pattern_exit_codes(self) -> None:
        self.assertEqual(mod.main(["is-managed-pattern", ".yoke/strategy/PAD.md"]), 0)
        self.assertEqual(mod.main(["is-managed-pattern", "README.md"]), 1)

    def test_is_managed_backlog_exit_codes(self) -> None:
        # Frontmatter-only change against HEAD exits 0; body change exits 1.
        with mock.patch.object(
            mod,
            "is_yoke_managed_backlog",
            return_value=True,
        ):
            self.assertEqual(mod.main(["is-managed-backlog", "backlog/1.md"]), 0)
        with mock.patch.object(
            mod,
            "is_yoke_managed_backlog",
            return_value=False,
        ):
            self.assertEqual(mod.main(["is-managed-backlog", "backlog/1.md"]), 1)

    def test_classify_dirty_repo_arg(self) -> None:
        with mock.patch.object(mod, "_cmd_classify_dirty", return_value=0) as mocked:
            self.assertEqual(
                mod.main(["classify-dirty", "--repo", "/tmp/example", "--exclude-worktrees"]),
                0,
            )
        mocked.assert_called_once_with(True, "/tmp/example")


if __name__ == "__main__":
    unittest.main()
