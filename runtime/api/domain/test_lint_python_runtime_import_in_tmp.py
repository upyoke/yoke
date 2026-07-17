"""Tests for yoke_core.domain.lint_python_runtime_import_in_tmp.

Covers the deny path (Python imports of `runtime.*` landing in /tmp),
the allowed shapes (non-Python content in /tmp, in-tree Python paths,
Python in /tmp that doesn't touch runtime imports), and the
audit-only suppression token.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_python_runtime_import_in_tmp as lint
from runtime.harness.hook_runner.types import Next, Outcome


def _payload(file_path: str, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }


def _record_for(payload: dict) -> "lint.HookContext":
    return lint._build_context_from_payload(payload)


class TestDenyPath(unittest.TestCase):
    """Python files under /tmp that import runtime.* must be refused."""

    def test_tmp_py_with_from_import_denied(self) -> None:
        content = (
            "from yoke_core.domain.yoke_function_dispatch import dispatch\n"
            "print('hi')\n"
        )
        reason = lint.evaluate_fields("/tmp/foo.py", content)
        self.assertIsNotNone(reason)
        self.assertIn("ModuleNotFoundError", reason)

    def test_tmp_py_with_plain_import_denied(self) -> None:
        content = "import runtime\nprint('hi')\n"
        self.assertIsNotNone(lint.evaluate_fields("/tmp/foo.py", content))

    def test_tmp_py_with_submodule_import_denied(self) -> None:
        content = "import yoke_core.cli.db_router\n"
        self.assertIsNotNone(lint.evaluate_fields("/tmp/foo.py", content))

    def test_tmp_py_with_split_package_imports_denied(self) -> None:
        for package in ("yoke_cli", "yoke_harness"):
            with self.subTest(package=package):
                content = f"import {package}\n"
                self.assertIsNotNone(lint.evaluate_fields("/tmp/foo.py", content))

    def test_var_folders_py_denied(self) -> None:
        # macOS TMPDIR root is /var/folders/...; same structural failure.
        content = "from runtime.api import service_client\n"
        path = "/var/folders/xx/yy/T/foo.py"
        self.assertIsNotNone(lint.evaluate_fields(path, content))

    def test_private_tmp_py_denied(self) -> None:
        # macOS /tmp is a symlink to /private/tmp — both should match.
        content = "import runtime\n"
        self.assertIsNotNone(lint.evaluate_fields("/private/tmp/foo.py", content))


class TestAllowedShapes(unittest.TestCase):
    """The lint stays out of legitimate shapes."""

    def test_tmp_markdown_allowed(self) -> None:
        # Markdown content in /tmp — no Python imports, no concern.
        content = "# Heading\n\nfrom runtime import something  (just docs)\n"
        self.assertIsNone(lint.evaluate_fields("/tmp/spec.md", content))

    def test_tmp_json_allowed(self) -> None:
        content = '{"function": "items.structured_field.replace"}'
        self.assertIsNone(lint.evaluate_fields("/tmp/envelope.json", content))

    def test_tmp_py_without_runtime_import_allowed(self) -> None:
        # A standalone /tmp Python script that doesn't touch Yoke is
        # fine — the lint only catches the failure mode it knows about.
        content = "print('hello world')\nimport json\n"
        self.assertIsNone(lint.evaluate_fields("/tmp/standalone.py", content))

    def test_in_tree_runtime_py_allowed(self) -> None:
        # Python under the repo tree with runtime imports — totally fine,
        # `from runtime.*` works because of the package layout.
        content = "from yoke_core.domain.sessions import register_session\n"
        path = "/Users/dev/yoke/runtime/api/tools/new_tool.py"
        self.assertIsNone(lint.evaluate_fields(path, content))

    def test_tmp_py_with_comment_mentioning_runtime_allowed(self) -> None:
        # Comments and docstring mentions are not import statements.
        content = (
            "# This script uses `from runtime.api import x` in another file.\n"
            "print('hi')\n"
        )
        self.assertIsNone(lint.evaluate_fields("/tmp/foo.py", content))

    def test_empty_content_allowed(self) -> None:
        self.assertIsNone(lint.evaluate_fields("/tmp/foo.py", ""))


class TestTmpYokeCheckoutExemption(unittest.TestCase):
    """A real Yoke checkout/worktree provisioned under /tmp resolves
    ``runtime.*`` natively from the worktree root, so its in-package
    Python must NOT be blocked. The exemption requires BOTH a ``.git``
    entry and ``pyproject.toml`` at the root AND the target under
    ``runtime/`` — a stray ``/tmp/foo.py`` still hits the lint."""

    _RUNTIME = "from yoke_core.domain.sessions import register_session\n"

    def setUp(self) -> None:
        # tempfile lands under the OS temp root; on macOS that is
        # /var/folders/... and on Linux /tmp — both recognized prefixes,
        # so the exemption path is exercised against a real tmp tree.
        self._tmp = tempfile.mkdtemp(prefix="lint-tmp-checkout-")
        if not self._tmp.startswith(lint._TMP_PREFIXES):
            self.skipTest(f"temp root {self._tmp} not under a tmp prefix")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_checkout(self, name: str, *, git_as_file: bool,
                       with_pyproject: bool) -> str:
        root = os.path.join(self._tmp, name)
        os.makedirs(os.path.join(root, "runtime", "api", "domain"),
                    exist_ok=True)
        if git_as_file:
            with open(os.path.join(root, ".git"), "w", encoding="utf-8") as fh:
                fh.write("gitdir: /elsewhere/.git/worktrees/wt\n")
        else:
            os.makedirs(os.path.join(root, ".git"), exist_ok=True)
        if with_pyproject:
            with open(os.path.join(root, "pyproject.toml"), "w",
                      encoding="utf-8") as fh:
                fh.write("[project]\nname = 'yoke'\n")
        return root

    def test_allows_runtime_import_in_tmp_checkout(self) -> None:
        root = self._make_checkout("yok1888-wf-items", git_as_file=False,
                                   with_pyproject=True)
        target = os.path.join(root, "runtime", "api", "domain", "foo.py")
        self.assertTrue(lint._is_tmp_python_path(target))  # still /tmp
        self.assertIsNone(lint.evaluate_fields(target, self._RUNTIME))

    def test_allows_runtime_import_in_tmp_linked_worktree(self) -> None:
        # Linked worktrees carry a ``.git`` *file*, not a directory.
        root = self._make_checkout("yok1888-wf-linked", git_as_file=True,
                                   with_pyproject=True)
        target = os.path.join(root, "runtime", "api", "test_foo.py")
        self.assertIsNone(lint.evaluate_fields(target, self._RUNTIME))

    def test_allows_package_import_in_tmp_checkout_package_source(self) -> None:
        root = self._make_checkout("yok1902-wf-package", git_as_file=False,
                                   with_pyproject=True)
        target = os.path.join(
            root,
            "packages",
            "yoke-core",
            "src",
            "yoke_core",
            "domain",
            "foo.py",
        )
        self.assertIsNone(lint.evaluate_fields(target, self._RUNTIME))

    def test_blocks_stray_tmp_script_no_checkout(self) -> None:
        target = os.path.join(self._tmp, "loose", "scratch.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        self.assertIsNotNone(lint.evaluate_fields(target, self._RUNTIME))

    def test_blocks_script_outside_runtime_in_checkout(self) -> None:
        root = self._make_checkout("yok1888-wf-scratch", git_as_file=False,
                                   with_pyproject=True)
        target = os.path.join(root, "scratch", "foo.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        self.assertIsNotNone(lint.evaluate_fields(target, self._RUNTIME))

    def test_blocks_when_git_present_but_no_pyproject(self) -> None:
        root = self._make_checkout("yok1888-wf-nopyproj", git_as_file=False,
                                   with_pyproject=False)
        target = os.path.join(root, "runtime", "api", "foo.py")
        self.assertIsNotNone(lint.evaluate_fields(target, self._RUNTIME))


class TestSuppressionToken(unittest.TestCase):
    """The bypass token is audit-only — the rule still denies."""

    def test_token_records_attempt_still_denies(self) -> None:
        content = (
            "# lint:no-tmp-runtime-import-check\n"
            "from runtime.api import service_client\n"
        )
        with mock.patch.object(lint, "_emit_denial") as emit_mock:
            decision = lint.evaluate(
                _record_for(_payload("/tmp/foo.py", content)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        self.assertEqual(
            decision.audit_fields["audit_outcome"], "suppression_attempted")
        self.assertEqual(
            emit_mock.call_args.kwargs["outcome"], "suppression_attempted")

    def test_token_on_allowed_shape_stays_noop(self) -> None:
        content = "# lint:no-tmp-runtime-import-check\nprint('hi')\n"
        with mock.patch.object(lint, "_emit_denial") as emit_mock:
            decision = lint.evaluate(
                _record_for(_payload("/tmp/foo.py", content)))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        emit_mock.assert_not_called()


class TestEvaluateTypedEntry(unittest.TestCase):
    """The typed entry returns DENY for the failing shape and NOOP for
    the allowed shapes."""

    def test_deny_envelope_emitted(self) -> None:
        payload = _payload("/tmp/foo.py", "import runtime\n")
        decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_noop_for_allowed_shape(self) -> None:
        payload = _payload("/tmp/foo.md", "# heading\n")
        decision = lint.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)


if __name__ == "__main__":  # pragma: no cover - direct run convenience
    unittest.main()
