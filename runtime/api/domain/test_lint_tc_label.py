"""Tests for yoke_core.domain.lint_tc_label (typed evaluate)."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from yoke_core.domain import lint_tc_label as mod
from runtime.harness.hook_runner.types import Next, Outcome


def _bash(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _write(file_path: str, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def _record_for(payload: dict):
    return mod._build_context_from_payload(payload)


class TestSequentialTCDetector(unittest.TestCase):
    def test_bare_numeric_label_detected(self) -> None:
        self.assertTrue(mod.is_sequential_tc("# TC-42"))

    def test_named_label_ignored(self) -> None:
        self.assertFalse(mod.is_sequential_tc("# TC-42-slow-path"))
        self.assertFalse(mod.is_sequential_tc("# TC-42_slow"))
        self.assertFalse(mod.is_sequential_tc("# TC-42alpha"))

    def test_mix_detects_any_sequential(self) -> None:
        self.assertTrue(mod.is_sequential_tc("TC-1-named and TC-2 trailing"))


class TestNumericHCFilename(unittest.TestCase):
    def test_matches(self) -> None:
        self.assertTrue(mod.has_numeric_hc_filename("test-doctor-hc12.sh"))
        self.assertTrue(
            mod.has_numeric_hc_filename(
                "/abs/path/.agents/skills/yoke/scripts/tests/test-doctor-hc99.sh"
            )
        )

    def test_descriptive_name_ok(self) -> None:
        self.assertFalse(mod.has_numeric_hc_filename("test-doctor-hc-schema-drift.sh"))

    def test_unrelated_file_ok(self) -> None:
        self.assertFalse(mod.has_numeric_hc_filename("test-yoke-db.sh"))


class TestBashTool(unittest.TestCase):
    def test_allow_unrelated_command(self) -> None:
        self.assertIsNone(mod.evaluate_payload(_bash("ls -la")))

    def test_suppression_comment_allows(self) -> None:
        cmd = (
            "cat > .agents/skills/yoke/scripts/tests/test-x.sh <<EOF\n"
            "# TC-7\nEOF\n# lint:no-tc-label-check"
        )
        self.assertIsNone(mod.evaluate_payload(_bash(cmd)))

    def test_write_redirect_with_tc_label_blocks(self) -> None:
        cmd = (
            'printf "TC-5" > '
            ".agents/skills/yoke/scripts/tests/test-x.sh"
        )
        reason = mod.evaluate_payload(_bash(cmd))
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("Sequential TC", reason)

    def test_heredoc_tc_label_blocks(self) -> None:
        cmd = (
            "cat > .agents/skills/yoke/scripts/tests/test-x.sh <<EOF\n"
            "echo TC-3\n"
            "EOF\n"
        )
        reason = mod.evaluate_payload(_bash(cmd))
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("heredoc", reason)

    def test_heredoc_named_label_ok(self) -> None:
        cmd = (
            "cat > .agents/skills/yoke/scripts/tests/test-x.sh <<EOF\n"
            "echo TC-3-named-path\n"
            "EOF\n"
        )
        self.assertIsNone(mod.evaluate_payload(_bash(cmd)))

    def test_numeric_hc_filename_creation_blocks(self) -> None:
        cmd = (
            "touch "
            ".agents/skills/yoke/scripts/tests/test-doctor-hc12.sh"
        )
        reason = mod.evaluate_payload(_bash(cmd))
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("Numeric HC", reason)

    def test_numeric_hc_mere_reference_ok(self) -> None:
        cmd = "grep test-doctor-hc42.sh /dev/null"
        self.assertIsNone(mod.evaluate_payload(_bash(cmd)))

    def test_sequential_tc_without_test_write_ok(self) -> None:
        # Not writing to a test file — should allow
        cmd = "echo 'TC-1 is a placeholder'"
        self.assertIsNone(mod.evaluate_payload(_bash(cmd)))

    def test_claude_compat_path_also_blocks(self) -> None:
        cmd = (
            "cat > .claude/skills/yoke/scripts/tests/test-y.sh <<EOF\n"
            "TC-1\n"
            "EOF\n"
        )
        reason = mod.evaluate_payload(_bash(cmd))
        self.assertIsNotNone(reason)


class TestWriteTool(unittest.TestCase):
    def test_suppression_in_content_allows(self) -> None:
        payload = _write(
            ".agents/skills/yoke/scripts/tests/test-x.sh",
            "TC-5\n# lint:no-tc-label-check\n",
        )
        self.assertIsNone(mod.evaluate_payload(payload))

    def test_numeric_hc_write_blocks(self) -> None:
        payload = _write(
            ".agents/skills/yoke/scripts/tests/test-doctor-hc42.sh",
            "echo ok",
        )
        reason = mod.evaluate_payload(payload)
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("Numeric HC", reason)

    def test_sequential_tc_in_test_file_blocks(self) -> None:
        payload = _write(
            ".agents/skills/yoke/scripts/tests/test-x.sh",
            "# TC-1\necho hi\n# TC-2\n",
        )
        reason = mod.evaluate_payload(payload)
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertIn("Sequential TC", reason)

    def test_tc_label_in_non_test_path_allowed(self) -> None:
        payload = _write("runtime/api/domain/foo.py", "# TC-5 placeholder")
        self.assertIsNone(mod.evaluate_payload(payload))

    def test_named_label_allowed(self) -> None:
        payload = _write(
            ".agents/skills/yoke/scripts/tests/test-x.sh",
            "# TC-1-slow-path\necho hi\n",
        )
        self.assertIsNone(mod.evaluate_payload(payload))


class TestEvaluate(unittest.TestCase):
    def test_allow_returns_noop(self) -> None:
        decision = mod.evaluate(_record_for(_bash("ls")))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertEqual(decision.message, "")

    def test_deny_carries_envelope_and_block(self) -> None:
        payload = _write(
            ".agents/skills/yoke/scripts/tests/test-x.sh", "TC-1\n"
        )
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
    def test_allow_produces_no_output(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(_bash("ls")))), \
             redirect_stdout(buf):
            rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_invalid_json_allows(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("garbage")), redirect_stdout(buf):
            rc = mod.main()
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_deny_prints_json(self) -> None:
        payload = json.dumps(
            _write(".agents/skills/yoke/scripts/tests/test-x.sh", "TC-1\n")
        )
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
