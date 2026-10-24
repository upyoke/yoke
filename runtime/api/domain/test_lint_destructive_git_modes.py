"""Tests for yoke_core.domain.lint_destructive_git (typed evaluate)."""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import shutil
import tempfile
import unittest
from unittest import mock

from yoke_core.domain import lint_destructive_git as ldg
from yoke_core.hooks.guard_denial_record import guard_audit_outcome
from yoke_core.hooks.types import Next, Outcome


from runtime.api.domain.destructive_git_test_helpers import (
    _payload,
    _record_for,
    _make_repo,
    _modify,
)


class TestModePinAndSuppression(unittest.TestCase):
    """Mode-pin verdict + AC-T3 suppression-token audit-only semantics."""

    def setUp(self):
        self.repo = _make_repo(initial_files={"a.txt": "v1\n"})
        _modify(self.repo, "a.txt", "v2\n")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_AC8_token_records_attempt_still_denies(self):
        cmd = (
            f"git -C {self.repo} reset --hard HEAD~1  # lint:no-uncommitted-wipe-check"
        )
        with mock.patch.object(ldg, "_read_mode", return_value="deny"):
            result = ldg.evaluate_payload(_payload(cmd))
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(outcome, "suppression_attempted")
        self.assertEqual(mode, "deny")
        self.assertIn("does NOT unblock", reason)

    def test_AC8_evaluate_token_still_denies_with_attempted_outcome(self):
        # AC-T3: suppression-token is audit-only; evaluate(record) still denies.
        cmd = (
            f"git -C {self.repo} reset --hard HEAD~1  # lint:no-uncommitted-wipe-check"
        )
        with mock.patch.object(ldg, "_read_mode", return_value="deny"):
            decision = ldg.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertEqual(
            decision.audit_fields["audit_outcome"], "suppression_attempted"
        )
        self.assertIn("does NOT unblock", decision.audit_fields["reason"])
        self.assertEqual(guard_audit_outcome(decision), "suppression_attempted")

    def test_AC9_warn_mode_returns_warn_no_deny_envelope(self):
        with mock.patch.object(ldg, "_read_mode", return_value="warn"):
            decision = ldg.evaluate(
                _record_for(_payload(f"git -C {self.repo} reset --hard HEAD~1"))
            )
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertEqual(decision.audit_fields["mode"], "warn")
        self.assertTrue(decision.audit_fields["reason"])
        self.assertEqual(guard_audit_outcome(decision), "warn")

    def test_AC9_deny_mode_emits_envelope(self):
        with mock.patch.object(ldg, "_read_mode", return_value="deny"):
            decision = ldg.evaluate(
                _record_for(_payload(f"git -C {self.repo} reset --hard HEAD~1"))
            )
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        self.assertEqual(guard_audit_outcome(decision), "denied")
        envelope = json.loads(render_codex_decision([decision], "PreToolUse")[0])
        self.assertEqual(envelope["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "BLOCKED", envelope["hookSpecificOutput"]["permissionDecisionReason"]
        )


class TestFailOpen(unittest.TestCase):
    def test_invalid_payload_returns_noop(self):
        decision = ldg.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertFalse(decision.block)

    def test_non_bash_tool_no_deny(self):
        result = ldg.evaluate_payload(
            {"tool_name": "Read", "tool_input": {"command": "git reset --hard"}}
        )
        self.assertIsNone(result)

    def test_non_git_repo_no_deny(self):
        d = tempfile.mkdtemp(prefix="ldg-non-git-")
        try:
            result = ldg.evaluate_payload(_payload(f"git -C {d} reset --hard HEAD~1"))
            self.assertIsNone(result)
        finally:
            shutil.rmtree(d, ignore_errors=True)
