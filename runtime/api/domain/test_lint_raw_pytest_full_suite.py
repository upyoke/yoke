"""Tests for yoke_core.domain.lint_raw_pytest_full_suite.

Covers the deny shape (a raw sweep naming every declared anchor), the
advisory shape (any other directory sweep, including a bare rootdir
run), the shapes that must stay silent (file-scoped runs, and any
invocation that already arbitrates for the admission slot), and the
warn-mode plus suppression-token contracts shared with the sibling
long-command lints.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_raw_pytest_full_suite as lint
from runtime.harness.hook_runner.types import Next, Outcome


def _payload(command: str, **extra) -> dict:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    payload.update(extra)
    return payload


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command))


def _anchor_sweep() -> str:
    return "uv run --frozen python3 -m pytest " + " ".join(
        f"{anchor}/" for anchor in lint.full_sweep_anchors()
    )


class TestAnchorsAreLiveConstants(unittest.TestCase):
    def test_anchors_resolve_from_the_selector_constant(self):
        from yoke_core.tools._impacted_import_index import TEST_ANCHORS

        self.assertEqual(
            lint.full_sweep_anchors(),
            tuple(anchor.strip("/") for anchor in TEST_ANCHORS),
        )

    def test_unreadable_anchors_degrade_to_advisory(self):
        with mock.patch.object(lint, "full_sweep_anchors", return_value=()):
            severity, _ = lint._classify(_anchor_sweep())
        self.assertEqual(severity, "sweep")


class TestDenyShape(unittest.TestCase):
    def test_whole_surface_sweep_denies(self):
        verdict = _eval(_anchor_sweep())
        self.assertIsNotNone(verdict)
        mode, reason, outcome = verdict
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("yoke watch pytest", reason)
        self.assertIn("admission slot", reason)

    def test_flag_values_are_not_read_as_paths(self):
        # `-n auto` and `-k expr` must not be mistaken for path operands,
        # and their presence must not hide the anchors either.
        command = _anchor_sweep() + " -n auto -k 'not slow' --tb=short"
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_bare_pytest_binary_is_matched(self):
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        mode, _, _ = _eval(f"pytest {anchors}")
        self.assertEqual(mode, "deny")

    def test_warn_mode_downgrades_without_unblocking_the_advice(self):
        mode, reason, outcome = _eval(_anchor_sweep(), mode="warn")
        self.assertEqual(mode, "warn")
        self.assertEqual(outcome, "warned")
        self.assertIn("yoke watch pytest", reason)

    def test_suppression_token_is_audited_not_honored(self):
        command = _anchor_sweep() + "  # lint:no-raw-pytest-check"
        mode, reason, outcome = _eval(command)
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn("does NOT unblock", reason)


class TestAdvisoryShape(unittest.TestCase):
    def test_single_directory_sweep_advises(self):
        mode, reason, outcome = _eval("python3 -m pytest runtime/api/domain/")
        self.assertEqual(mode, "warn")
        self.assertEqual(outcome, "warned")
        self.assertIn("runtime/api/domain", reason)

    def test_pathless_run_sweeps_the_rootdir(self):
        mode, reason, _ = _eval("uv run --frozen python3 -m pytest -q")
        self.assertEqual(mode, "warn")
        self.assertIn("the whole rootdir", reason)

    def test_a_directory_sweep_never_denies_even_in_deny_mode(self):
        # Only the unambiguous whole-surface shape is deniable; a narrow
        # sweep may be a deliberate investigation.
        mode, _, _ = _eval("pytest tests/", mode="deny")
        self.assertEqual(mode, "warn")


class TestSilentShapes(unittest.TestCase):
    def test_file_scoped_run_is_not_matched(self):
        self.assertIsNone(
            _eval("python3 -m pytest runtime/api/domain/test_thing.py -k foo")
        )

    def test_watcher_wrapper_is_not_matched(self):
        self.assertIsNone(_eval(_anchor_sweep().replace(
            "python3 -m pytest", "python3 -m yoke_core.tools.watch_pytest --"
        )))

    def test_yoke_watch_spelling_is_not_matched(self):
        self.assertIsNone(
            _eval("yoke watch pytest -- runtime/api/ runtime/harness/ tests/")
        )

    def test_qa_case_run_is_not_matched(self):
        self.assertIsNone(_eval("yoke qa case run --requirement-id 7"))

    def test_non_bash_tool_is_not_matched(self):
        payload = _payload(_anchor_sweep())
        payload["tool_name"] = "Read"
        self.assertIsNone(lint.evaluate_payload(payload))


class TestDecisionEnvelope(unittest.TestCase):
    def test_deny_stops_the_chain_with_a_permission_envelope(self):
        with mock.patch.object(lint, "_read_mode", return_value="deny"):
            with mock.patch.object(lint, "_emit_audit_event"):
                decision = lint.evaluate(
                    lint._build_context_from_payload(_payload(_anchor_sweep()))
                )
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        self.assertIn("permissionDecision", decision.message)

    def test_clean_command_continues(self):
        decision = lint.evaluate(
            lint._build_context_from_payload(_payload("git status --short"))
        )
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)


if __name__ == "__main__":
    unittest.main()
