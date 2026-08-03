"""Config-source resolution for the destructive-git guard.

Two behaviors are covered here, both about *which* ``.yoke/lint-config``
decides a refusal:

* the enforcement mode is read from the checkout the refused command
  targets, so policy comes from the same tree whose state is judged;
* the narrative names the resolved config file, so editing a different
  copy is visible rather than presenting as an edit that did nothing.

These tests deliberately do not stub ``_read_mode`` — the resolution path
is the thing under test.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_config
from yoke_core.domain import lint_destructive_git as ldg

GUARD_LINE_DENY = "lint_destructive_git=deny\n"
GUARD_LINE_WARN = "lint_destructive_git=warn # allow-warn\n"


def _git_run(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


class ConfigResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roots: list[str] = []
        lint_config.reset_cache()

    def tearDown(self) -> None:
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)
        lint_config.reset_cache()

    def _repo(self, guard_line: str) -> str:
        root = tempfile.mkdtemp(prefix="yoke-lint-cfg-")
        self.roots.append(root)
        _git_run(root, "init", "-q", "-b", "main")
        _git_run(root, "config", "user.email", "test@example.invalid")
        _git_run(root, "config", "user.name", "Test")
        (pathlib.Path(root) / "tracked.txt").write_text("v1\n")
        _git_run(root, "add", "tracked.txt")
        _git_run(root, "commit", "-q", "-m", "initial")

        config = pathlib.Path(root) / ".yoke" / "lint-config"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(guard_line)
        # Untracked file so clean_force has real threatened state to report.
        (pathlib.Path(root) / "junk.tmp").write_text("x")
        return root

    def _evaluate_clean(self, repo: str):
        return ldg.evaluate_payload(_payload(f"git -C {repo} clean -f"))

    def test_mode_comes_from_the_targeted_checkout(self):
        """A checkout whose config says warn is not judged by another's deny."""
        warn_repo = self._repo(GUARD_LINE_WARN)
        result = self._evaluate_clean(warn_repo)
        self.assertIsNotNone(result, "clean -f with untracked state should trip")
        self.assertEqual(result[0], "warn")

    def test_deny_checkout_still_denies(self):
        deny_repo = self._repo(GUARD_LINE_DENY)
        result = self._evaluate_clean(deny_repo)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_two_checkouts_resolve_independently(self):
        """The guard reads each target's own config, not one shared root."""
        warn_repo = self._repo(GUARD_LINE_WARN)
        deny_repo = self._repo(GUARD_LINE_DENY)
        self.assertEqual(self._evaluate_clean(warn_repo)[0], "warn")
        self.assertEqual(self._evaluate_clean(deny_repo)[0], "deny")

    def test_narrative_names_the_resolved_config_file(self):
        deny_repo = self._repo(GUARD_LINE_DENY)
        reason = self._evaluate_clean(deny_repo)[1]
        expected = str(pathlib.Path(deny_repo) / ".yoke" / "lint-config")
        self.assertIn(expected, reason)
        self.assertIn("lint_destructive_git=deny", reason)

    def test_narrative_still_reports_threatened_state(self):
        """The provenance line supplements the existing narrative, not replaces it."""
        deny_repo = self._repo(GUARD_LINE_DENY)
        reason = self._evaluate_clean(deny_repo)[1]
        self.assertIn("junk.tmp", reason)
        self.assertIn("Remediation:", reason)


class DescribeConfigSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        lint_config.reset_cache()

    def tearDown(self) -> None:
        lint_config.reset_cache()

    def test_names_path_and_effective_mode(self):
        root = tempfile.mkdtemp(prefix="yoke-lint-desc-")
        self.addCleanup(shutil.rmtree, root, True)
        note = lint_config.describe_config_source(
            "lint_destructive_git", "deny", root=root)
        self.assertIn(str(pathlib.Path(root) / ".yoke" / "lint-config"), note)
        self.assertIn("lint_destructive_git=deny", note)

    def test_reports_the_passed_mode_not_a_second_lookup(self):
        """Callers resolving from a payload snapshot still get a truthful note."""
        root = tempfile.mkdtemp(prefix="yoke-lint-desc-")
        self.addCleanup(shutil.rmtree, root, True)
        config = pathlib.Path(root) / ".yoke" / "lint-config"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(GUARD_LINE_DENY)
        note = lint_config.describe_config_source(
            "lint_destructive_git", "warn", root=root)
        self.assertIn("lint_destructive_git=warn", note)

    def test_handles_absent_workspace_root(self):
        with mock.patch.object(lint_config, "_workspace_root", return_value=None):
            note = lint_config.describe_config_source("lint_destructive_git", "deny")
        self.assertIn("no .yoke/lint-config found", note)
        self.assertIn("lint_destructive_git=deny", note)


if __name__ == "__main__":
    unittest.main()
