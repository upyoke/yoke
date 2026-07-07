"""Tests for yoke_core.domain.lint_write_path (typed evaluate)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from yoke_core.domain import lint_write_path as mod
from runtime.harness.hook_runner.types import Next, Outcome


def _write(file_path: str, content: str = "") -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def _record_for(payload: dict):
    return mod._build_context_from_payload(payload)


class TestDollarDollar(unittest.TestCase):
    def test_literal_dollar_dollar_blocks(self) -> None:
        reason = mod.evaluate_payload(_write("/tmp/scratch.$$", "hello"))
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("literal \"$$\"", reason)

    def test_clean_path_allows(self) -> None:
        self.assertIsNone(mod.evaluate_payload(_write("/tmp/scratch.abc", "hello")))

    def test_empty_path_allows(self) -> None:
        self.assertIsNone(mod.evaluate_payload(_write("", "hello")))


class TestWorkflowDetection(unittest.TestCase):
    def test_github_workflow_recognized(self) -> None:
        self.assertTrue(mod._is_workflow_yaml(".github/workflows/deploy.yml"))
        self.assertTrue(mod._is_workflow_yaml(".github/workflows/deploy.yaml"))

    def test_template_workflow_recognized(self) -> None:
        self.assertTrue(
            mod._is_workflow_yaml("templates/webapp/ops/deploy.yml")
        )

    def test_project_workflow_recognized(self) -> None:
        self.assertTrue(
            mod._is_workflow_yaml("projects/buzz/.github/workflows/deploy.yml")
        )
        self.assertTrue(
            mod._is_workflow_yaml("projects/buzz/ops/deploy.yaml")
        )

    def test_non_workflow_ignored(self) -> None:
        self.assertFalse(mod._is_workflow_yaml("src/foo.yml"))
        self.assertFalse(mod._is_workflow_yaml(".github/workflows/deploy.txt"))


class TestScanSecretsInIf(unittest.TestCase):
    def test_secrets_in_single_line_if(self) -> None:
        content = "jobs:\n  deploy:\n    if: ${{ secrets.X != '' }}\n"
        violations = mod._scan_secrets_in_if(content)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][0], 3)

    def test_secrets_in_multiline_if(self) -> None:
        # Unclosed ${{ on an if: line — subsequent lines with secrets.* are
        # still flagged until the closing }} appears.
        content = (
            "jobs:\n"
            "  deploy:\n"
            "    if: ${{\n"
            "      secrets.X != ''\n"
            "      }}\n"
        )
        violations = mod._scan_secrets_in_if(content)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0][0], 4)

    def test_secrets_outside_if_ignored(self) -> None:
        content = "env:\n  X: ${{ secrets.X }}\n"
        self.assertEqual(mod._scan_secrets_in_if(content), [])


class TestEvaluatePayload(unittest.TestCase):
    def test_workflow_with_secrets_in_if_blocks(self) -> None:
        content = "jobs:\n  deploy:\n    if: ${{ secrets.X != '' }}\n    runs-on: ubuntu\n"
        reason = mod.evaluate_payload(
            _write(".github/workflows/deploy.yml", content)
        )
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("secrets.*", reason)
        self.assertIn(".github/workflows/deploy.yml", reason)

    def test_workflow_without_secrets_in_if_allowed(self) -> None:
        content = (
            "jobs:\n"
            "  deploy:\n"
            "    env:\n"
            "      X: ${{ secrets.X }}\n"
            "    runs-on: ubuntu\n"
        )
        self.assertIsNone(
            mod.evaluate_payload(_write(".github/workflows/deploy.yml", content))
        )

    def test_non_workflow_with_secrets_allowed(self) -> None:
        self.assertIsNone(
            mod.evaluate_payload(
                _write("src/foo.yaml", "if: ${{ secrets.X != '' }}")
            )
        )

    def test_non_dict_tool_input_handled(self) -> None:
        payload = {"tool_name": "Write", "tool_input": None}
        self.assertIsNone(mod.evaluate_payload(payload))


class TestEvaluate(unittest.TestCase):
    def test_allow_returns_noop(self) -> None:
        decision = mod.evaluate(_record_for(_write("/tmp/clean.txt", "x")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertEqual(decision.message, "")

    def test_deny_carries_envelope_and_block(self) -> None:
        payload = _write("/tmp/foo.tmp.$$", "x")
        with mock.patch.object(mod, "_emit_denial") as emit_mock:
            decision = mod.evaluate(_record_for(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        self.assertTrue(decision.block)
        parsed = json.loads(decision.message)
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        emit_mock.assert_called_once()


class TestMain(unittest.TestCase):
    def test_invalid_json_allows(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("not-json")), redirect_stdout(buf):
            rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_deny_prints_json(self) -> None:
        payload = json.dumps(_write("/tmp/foo.tmp.$$", "x"))
        buf = io.StringIO()
        with mock.patch.object(mod, "_emit_denial"), \
             mock.patch("sys.stdin", io.StringIO(payload)), \
             redirect_stdout(buf):
            rc = mod.main()
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue().strip())
        self.assertEqual(
            parsed["hookSpecificOutput"]["permissionDecision"], "deny"
        )


if __name__ == "__main__":
    unittest.main()
