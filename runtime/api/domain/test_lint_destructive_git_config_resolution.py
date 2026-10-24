"""Config-source resolution for the destructive-git guard.

The guard never reads its own mode: it always returns its natural deny, and
:func:`yoke_core.hooks.mode_gate.apply_mode` applies the ``.yoke/lint-config``
under the hook's target root. The deny message still names the config file
under the targeted checkout, with the fixed deny value it renders under.
These tests run the real resolution path (no stubbed mode).
"""

from __future__ import annotations

import dataclasses
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_config
from yoke_core.domain import lint_destructive_git as ldg
from yoke_core.hooks import mode_gate
from yoke_core.hooks.types import Outcome

MODULE_ID = "yoke_core.domain.lint_destructive_git"
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

    def _gated_clean(self, repo: str):
        context = dataclasses.replace(
            ldg._build_context_from_payload(_payload(f"git -C {repo} clean -f")),
            target_root=repo,
        )
        decision = ldg.evaluate(context)
        self.assertIs(decision.outcome, Outcome.DENY)
        return mode_gate.apply_mode(decision, MODULE_ID, context=context)

    def test_deny_config_keeps_the_block(self):
        gated = self._gated_clean(self._repo(GUARD_LINE_DENY))
        self.assertIs(gated.outcome, Outcome.DENY)
        self.assertTrue(gated.block)
        self.assertEqual(gated.audit_fields["policy_mode"], "deny")

    def test_warn_config_downgrades_the_block(self):
        gated = self._gated_clean(self._repo(GUARD_LINE_WARN))
        self.assertIs(gated.outcome, Outcome.WARN)
        self.assertFalse(gated.block)
        self.assertEqual(gated.audit_fields["policy_mode"], "warn")

    def test_narrative_names_the_resolved_config_file(self):
        deny_repo = self._repo(GUARD_LINE_DENY)
        reason = ldg.evaluate_payload(_payload(f"git -C {deny_repo} clean -f"))[0]
        expected = str(pathlib.Path(deny_repo) / ".yoke" / "lint-config")
        self.assertIn(expected, reason)
        self.assertIn("lint_destructive_git=deny", reason)

    def test_narrative_reports_threatened_state(self):
        deny_repo = self._repo(GUARD_LINE_DENY)
        reason = ldg.evaluate_payload(_payload(f"git -C {deny_repo} clean -f"))[0]
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
