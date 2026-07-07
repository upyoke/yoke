"""Tests for yoke_core.domain.lint_git_stash_arg_order.

Cover the four canonical shapes:

- `-m` BEFORE `--`           -> allowed
- `--message` BEFORE `--`    -> allowed
- `-m` AFTER `--`            -> denied
- `--message` AFTER `--`     -> denied (the YOK-1784 forensic shape)

Plus the suppression-token audit-only and warn-mode contracts that mirror
the destructive-git lint family.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_git_stash_arg_order as lsao
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


def _record_for(payload: dict) -> "lsao.HookContext":
    return lsao._build_context_from_payload(payload)


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lsao, "_read_mode", return_value=mode):
        return lsao.evaluate_payload(_payload(command))


class TestIsStashPush(unittest.TestCase):
    def test_bare_stash_is_push(self):
        self.assertTrue(lsao._is_stash_push(["stash"]))

    def test_stash_push_explicit(self):
        self.assertTrue(lsao._is_stash_push(["stash", "push"]))

    def test_stash_save_legacy(self):
        self.assertTrue(lsao._is_stash_push(["stash", "save"]))

    def test_stash_with_flag_first_is_push(self):
        self.assertTrue(lsao._is_stash_push(["stash", "-u"]))
        self.assertTrue(lsao._is_stash_push(["stash", "-m", "x"]))

    def test_stash_non_push_subcommands(self):
        for sub in ("drop", "clear", "pop", "list", "show", "apply",
                    "branch", "create", "store"):
            self.assertFalse(lsao._is_stash_push(["stash", sub]),
                f"{sub} must classify as non-push")

    def test_non_stash_verb(self):
        self.assertFalse(lsao._is_stash_push(["reset", "--hard"]))
        self.assertFalse(lsao._is_stash_push([]))


class TestFindMessageAfterDashDash(unittest.TestCase):
    def test_no_dashdash_returns_none(self):
        self.assertIsNone(
            lsao._find_message_after_dashdash(["stash", "push", "-m", "msg"]))

    def test_message_before_dashdash_returns_none(self):
        self.assertIsNone(
            lsao._find_message_after_dashdash(
                ["stash", "push", "-m", "msg", "--", "a.txt"]))

    def test_short_flag_after_dashdash_detected(self):
        hit = lsao._find_message_after_dashdash(
            ["stash", "push", "--", "a.txt", "-m", "msg"])
        self.assertEqual(hit, ("-m", 2, 4))

    def test_long_flag_after_dashdash_detected(self):
        hit = lsao._find_message_after_dashdash(
            ["stash", "push", "--", "a.txt", "--message", "msg"])
        self.assertEqual(hit, ("--message", 2, 4))

    def test_long_flag_equals_form_after_dashdash_detected(self):
        hit = lsao._find_message_after_dashdash(
            ["stash", "push", "--", "a.txt", "--message=msg"])
        self.assertIsNotNone(hit)
        # ``--`` is at index 2; ``--message=msg`` is at index 4.
        self.assertEqual(hit, ("--message=", 2, 4))


class TestEvaluatePayloadAllowed(unittest.TestCase):
    """Correct shapes must NOT trigger the deny."""

    def test_AC1_short_flag_before_dashdash_allowed(self):
        self.assertIsNone(_eval('git stash push -u -m "reason" -- a.txt b.txt'))

    def test_AC1_long_flag_before_dashdash_allowed(self):
        self.assertIsNone(_eval('git stash push --message "reason" -- a.txt'))

    def test_AC1_no_dashdash_at_all_allowed(self):
        self.assertIsNone(_eval('git stash push -m "reason"'))

    def test_AC1_bare_stash_allowed(self):
        self.assertIsNone(_eval('git stash'))
        self.assertIsNone(_eval('git stash push'))
        self.assertIsNone(_eval('git stash push -u'))

    def test_AC1_non_push_subcommands_allowed(self):
        # Those have their own destructive-git lint coverage; this lint
        # is scoped to push-shape misorder only.
        for cmd in ('git stash drop', 'git stash clear', 'git stash pop',
                    'git stash list', 'git stash show -p stash@{0}'):
            self.assertIsNone(_eval(cmd), f"must not trigger: {cmd}")

    def test_AC1_dash_C_prefix_allowed_when_correctly_ordered(self):
        self.assertIsNone(
            _eval('git -C /tmp/x stash push -m "reason" -- a.txt'))

    def test_AC1_non_stash_command_ignored(self):
        self.assertIsNone(_eval('git commit -m "msg" -- a.txt'))


class TestEvaluatePayloadDenied(unittest.TestCase):
    """The YOK-1784 forensic shape and siblings must deny."""

    def test_AC2_short_flag_after_dashdash_denies(self):
        result = _eval('git stash push -u -- a.txt b.txt -m "reason"')
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("`-m`", reason)
        self.assertIn("BEFORE `--`", reason)

    def test_AC2_long_flag_after_dashdash_denies_forensic_shape(self):
        # The exact YOK-1784 shape — long flag with double-quoted value
        # after a list of pathspecs and `--`.
        cmd = ('git -C .worktrees/YOK-1788 stash push -u -- '
               'file1 file2 --message "YOK-1788: rationale"')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("--message", reason)
        # Safe shape suggestion must include the canonical reordering.
        self.assertIn('git stash push -u -m "reason" -- <paths>', reason)

    def test_AC2_long_flag_equals_form_after_dashdash_denies(self):
        result = _eval('git stash push -u -- a.txt --message=reason')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")
        self.assertIn("--message=", result[1])

    def test_AC2_bare_stash_with_misordered_message_denies(self):
        # `git stash` defaults to push; misorder applies the same way.
        result = _eval('git stash -- a.txt -m "reason"')
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_AC2_chained_invocations_inspected(self):
        cmd = ('git status && git stash push -u -- a.txt -m "reason"')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")


class TestSuppressionTokenAudit(unittest.TestCase):
    """Suppression token is recorded as audit evidence but does NOT unblock."""

    def test_AC7_token_records_attempt_still_denies(self):
        cmd = ('git stash push -u -- a.txt -m "reason"  '
               '# lint:no-stash-arg-order-check')
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(outcome, "suppression_attempted")
        self.assertEqual(mode, "deny")
        self.assertIn("does NOT unblock", reason)

    def test_AC7_evaluate_still_denies_with_attempted_outcome(self):
        cmd = ('git stash push -u -- a.txt -m "reason"  '
               '# lint:no-stash-arg-order-check')
        with mock.patch.object(lsao, "_read_mode", return_value="deny"), \
             mock.patch.object(lsao, "_emit_audit_event") as emit_mock:
            decision = lsao.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        # outcome arg is the 4th positional (payload, reason, mode, outcome).
        self.assertEqual(emit_mock.call_args.args[3], "suppression_attempted")


class TestModePin(unittest.TestCase):
    def test_AC9_warn_mode_returns_warn_no_deny_envelope(self):
        with mock.patch.object(lsao, "_read_mode", return_value="warn"), \
             mock.patch.object(lsao, "_emit_audit_event"):
            decision = lsao.evaluate(_record_for(
                _payload('git stash push -u -- a.txt -m "reason"')))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)

    def test_AC9_deny_mode_emits_envelope(self):
        with mock.patch.object(lsao, "_read_mode", return_value="deny"), \
             mock.patch.object(lsao, "_emit_audit_event"):
            decision = lsao.evaluate(_record_for(
                _payload('git stash push -u -- a.txt -m "reason"')))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(
            envelope["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "BLOCKED",
            envelope["hookSpecificOutput"]["permissionDecisionReason"])


class TestFailOpen(unittest.TestCase):
    def test_invalid_payload_returns_noop(self):
        decision = lsao.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertFalse(decision.block)

    def test_non_bash_tool_no_deny(self):
        result = lsao.evaluate_payload({"tool_name": "Read",
            "tool_input": {"command": 'git stash push -- a.txt -m x'}})
        self.assertIsNone(result)

    def test_empty_command_no_deny(self):
        self.assertIsNone(_eval(''))


if __name__ == "__main__":
    unittest.main()
