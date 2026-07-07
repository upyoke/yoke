"""Tests for yoke_core.domain.lint_pipe_to_truncator.

Covers the observed gap shape (foreground watcher piped to ``tail``),
the bare/`-m` pytest shapes, the truncator-after-grep chain, separator
boundaries (``;``/``&&``/``||``/newline do NOT join a pipe), the
``--print-streaming-pair`` instant exemption, short-adapter non-matches,
and the warn-mode + suppression-token contracts shared with the
stash-arg-order lint family.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_pipe_to_truncator as lptt
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


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lptt, "_read_mode", return_value=mode):
        return lptt.evaluate_payload(_payload(command))


class TestHitShapes(unittest.TestCase):
    def test_watch_pytest_piped_to_tail(self):
        # The literal observed gap shape from the field-note evidence.
        verdict = _eval(
            "python3 -m yoke_core.tools.watch_pytest -- runtime/api/ -q 2>&1 | tail -8"
        )
        self.assertIsNotNone(verdict)
        mode, reason, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("watch_pytest", reason)

    def test_watch_doctor_piped_to_head(self):
        self.assertIsNotNone(
            _eval("python3 -m yoke_core.tools.watch_doctor -- --quick | head -20")
        )

    def test_bare_pytest_piped_to_tail(self):
        self.assertIsNotNone(_eval("pytest runtime/api/ -q | tail -5"))

    def test_python_m_pytest_piped_to_tail(self):
        self.assertIsNotNone(_eval("python3 -m pytest runtime/api/ -q 2>&1 | tail -3"))

    def test_env_prefixed_pytest_piped(self):
        self.assertIsNotNone(
            _eval("YOKE_PG_DSN=postgres://x pytest runtime/api/test_x.py | tail -2")
        )

    def test_truncator_after_grep_stage(self):
        self.assertIsNotNone(
            _eval("python3 -m pytest runtime/api/ 2>&1 | grep -E 'FAIL' | tail -10")
        )

    def test_doctor_engine_piped(self):
        self.assertIsNotNone(
            _eval("python3 -m yoke_core.engines.doctor --quick 2>&1 | tail -40")
        )

    def test_run_tests_piped(self):
        self.assertIsNotNone(
            _eval("python3 -m yoke_core.tools.run_tests 2>&1 | head")
        )

    def test_venv_pytest_path_piped(self):
        self.assertIsNotNone(_eval("./venv/bin/pytest -q | tail -4"))


class TestNonMatches(unittest.TestCase):
    def test_bare_watcher_no_pipe_allowed(self):
        self.assertIsNone(
            _eval("python3 -m yoke_core.tools.watch_pytest -- runtime/api/ -q")
        )

    def test_capture_first_shape_allowed(self):
        self.assertIsNone(
            _eval('pytest runtime/api/ -q >"$_tmp" 2>&1; tail -80 "$_tmp"')
        )

    def test_separator_does_not_join_pipe(self):
        # Truncator in a LATER command (after ;, &&, newline) is post-completion
        # inspection, not a live pipe.
        self.assertIsNone(_eval("python3 -m pytest -q x.py && tail -80 /tmp/cap"))
        self.assertIsNone(_eval("python3 -m pytest -q x.py\ntail -80 /tmp/cap"))
        self.assertIsNone(_eval("python3 -m pytest -q x.py || tail -80 /tmp/cap"))

    def test_short_adapter_pipe_not_matched(self):
        # Short Yoke adapters are the shell-payload lint's domain, not ours.
        self.assertIsNone(_eval("yoke items get 42 status | head -1"))
        self.assertIsNone(_eval("git log --oneline | head -5"))

    def test_print_streaming_pair_exempt(self):
        self.assertIsNone(
            _eval(
                "python3 -m yoke_core.tools.watch_pytest --print-streaming-pair -- runtime/api/ | head -3"
            )
        )

    def test_pytest_word_in_argument_not_matched(self):
        self.assertIsNone(_eval("echo pytest | tail -1"))
        self.assertIsNone(_eval("rg -n pytest runtime/api/conftest.py | head -3"))

    def test_pipe_to_non_truncator_allowed(self):
        # The named clause is pipe-to-truncator; grep-only chains are the
        # polling/streaming rules' domain.
        self.assertIsNone(
            _eval("python3 -m pytest -q x.py 2>&1 | grep --line-buffered FAIL")
        )

    def test_non_bash_tool_ignored(self):
        payload = _payload("python3 -m pytest | tail -2")
        payload["tool_name"] = "Edit"
        with mock.patch.object(lptt, "_read_mode", return_value="deny"):
            self.assertIsNone(lptt.evaluate_payload(payload))


class TestModesAndSuppression(unittest.TestCase):
    def test_warn_mode_warns_not_denies(self):
        verdict = _eval("python3 -m pytest -q | tail -2", mode="warn")
        self.assertIsNotNone(verdict)
        mode, reason, outcome = verdict
        self.assertEqual(mode, "warn")
        self.assertIn("[mode=warn]", reason)
        self.assertEqual(outcome, "denied")

    def test_suppression_token_audit_only(self):
        verdict = _eval(
            "python3 -m pytest -q | tail -2  # lint:no-pipe-truncator-check"
        )
        self.assertIsNotNone(verdict)
        mode, reason, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn("does NOT unblock", reason)

    def test_evaluate_deny_decision_shape(self):
        payload = _payload("python3 -m pytest -q | tail -2")
        with mock.patch.object(lptt, "_read_mode", return_value="deny"), \
                mock.patch.object(lptt, "_emit_audit_event") as emit:
            decision = lptt.evaluate(lptt._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        emit.assert_called_once()

    def test_evaluate_warn_decision_shape(self):
        payload = _payload("python3 -m pytest -q | tail -2")
        with mock.patch.object(lptt, "_read_mode", return_value="warn"), \
                mock.patch.object(lptt, "_emit_audit_event"):
            decision = lptt.evaluate(lptt._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertFalse(decision.block)

    def test_noop_on_clean_command(self):
        decision = lptt.evaluate(
            lptt._build_context_from_payload(_payload("git status"))
        )
        self.assertIs(decision.outcome, Outcome.NOOP)

    def test_reason_names_both_hazards_and_correct_shape(self):
        verdict = _eval("python3 -m pytest -q | tail -2")
        _, reason, _ = verdict
        self.assertIn("exit code", reason)
        self.assertIn("failure context", reason)
        self.assertIn("capture-first", reason)


if __name__ == "__main__":
    unittest.main()
