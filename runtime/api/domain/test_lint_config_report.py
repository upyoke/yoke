"""Enforcement-state reporting for .yoke/lint-config.

The report exists to surface two silent conditions: a config copy that is
not the one being read, and a declared ``warn`` that the protected-guard
clamp quietly returns to ``deny``.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from yoke_contracts.hook_runner import lint_policy
from yoke_core.domain import lint_config_report as report


def _write_config(root: str, text: str) -> None:
    cfg = pathlib.Path(root).joinpath(*lint_policy.CONFIG_RELPATH)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text)


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.roots: list[str] = []

    def tearDown(self) -> None:
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def _root(self, text: str | None = None) -> str:
        root = tempfile.mkdtemp(prefix="yoke-lint-report-")
        self.roots.append(root)
        if text is not None:
            _write_config(root, text)
        return root

    def _guard(self, rep: report.ConfigReport, name: str) -> report.GuardReport:
        for guard in rep.guards:
            if guard.guard == name:
                return guard
        raise AssertionError(f"guard {name} missing from report")

    def test_protected_warn_without_token_is_reported_as_clamped(self):
        root = self._root("lint_destructive_git=warn\n")
        guard = self._guard(report.build_report(root), "lint_destructive_git")
        self.assertEqual(guard.declared_mode, lint_policy.WARN)
        self.assertEqual(guard.effective_mode, lint_policy.DENY)
        self.assertTrue(guard.clamped)

    def test_protected_warn_with_token_takes_effect(self):
        root = self._root("lint_destructive_git=warn # allow-warn\n")
        guard = self._guard(report.build_report(root), "lint_destructive_git")
        self.assertEqual(guard.effective_mode, lint_policy.WARN)
        self.assertFalse(guard.clamped)

    def test_unprotected_warn_needs_no_token(self):
        root = self._root("lint_tc_label=warn\n")
        guard = self._guard(report.build_report(root), "lint_tc_label")
        self.assertEqual(guard.effective_mode, lint_policy.WARN)
        self.assertFalse(guard.clamped)

    def test_undeclared_guard_reports_default_without_claiming_a_declaration(self):
        root = self._root("")
        guard = self._guard(report.build_report(root), "lint_destructive_git")
        self.assertIsNone(guard.declared_mode)
        self.assertFalse(guard.declared)
        self.assertEqual(guard.effective_mode, lint_policy.DENY)
        self.assertFalse(guard.clamped)

    def test_every_catalog_guard_is_reported(self):
        rep = report.build_report(self._root(""))
        self.assertEqual(
            {g.guard for g in rep.guards},
            {spec.guard for spec in lint_policy.GUARD_CATALOG},
        )

    def test_missing_config_is_flagged_rather_than_silently_defaulted(self):
        rep = report.build_report(self._root())
        self.assertFalse(rep.config_exists)
        self.assertIsNotNone(rep.config_path)

    def test_explicit_root_is_reported_as_explicit(self):
        rep = report.build_report(self._root(""))
        self.assertEqual(rep.root_source, report.SOURCE_EXPLICIT)
        self.assertIsNone(rep.root_env_var)

    def test_env_var_root_names_the_winning_variable(self):
        root = self._root("")
        with mock.patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": root}, clear=False):
            rep = report.build_report()
        self.assertEqual(rep.root_env_var, "CLAUDE_PROJECT_DIR")
        self.assertEqual(rep.root, root)

    def test_env_var_precedence_matches_resolution_order(self):
        first = self._root("")
        second = self._root("")
        env = {"YOKE_TARGET_REPO_ROOT": first, "CLAUDE_PROJECT_DIR": second}
        with mock.patch.dict("os.environ", env, clear=False):
            rep = report.build_report()
        self.assertEqual(rep.root_env_var, "YOKE_TARGET_REPO_ROOT")


class RenderTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="yoke-lint-render-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_clamped_guard_is_called_out_in_the_summary(self):
        _write_config(self.root, "lint_destructive_git=warn\n")
        text = report.render_text(report.build_report(self.root))
        self.assertIn("clamped to deny", text)
        self.assertIn(lint_policy.ALLOW_WARN_TOKEN, text)
        self.assertIn("NOT in force", text)

    def test_clean_config_has_no_not_in_force_summary(self):
        _write_config(self.root, "lint_destructive_git=deny\n")
        text = report.render_text(report.build_report(self.root))
        self.assertNotIn("NOT in force", text)

    def test_text_names_the_resolved_config_path(self):
        _write_config(self.root, "lint_destructive_git=deny\n")
        text = report.render_text(report.build_report(self.root))
        expected = str(pathlib.Path(self.root).joinpath(*lint_policy.CONFIG_RELPATH))
        self.assertIn(expected, text)

    def test_missing_config_is_marked_in_the_rendered_text(self):
        text = report.render_text(report.build_report(self.root))
        self.assertIn("MISSING", text)


if __name__ == "__main__":
    unittest.main()
