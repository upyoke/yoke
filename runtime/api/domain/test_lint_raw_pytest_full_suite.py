"""Tests for yoke_core.domain.lint_raw_pytest_full_suite.

Covers the deny shape (a raw sweep naming every declared anchor), the
advisory shape (any other directory sweep, including a bare rootdir
run), the shapes that must stay silent (file-scoped runs, and any
invocation that already arbitrates for the admission slot), and the
suppression-token contract shared with the sibling long-command lints.
Policy warn mode is applied centrally by ``mode_gate``.
"""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import lint_raw_pytest_full_suite as lint
from yoke_core.hooks.guard_denial_record import guard_audit_outcome
from yoke_core.hooks.types import Next, Outcome


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


def _eval(command: str):
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
        reason, outcome = verdict
        self.assertEqual(outcome, "denied")
        self.assertIn("yoke watch pytest", reason)
        self.assertIn("admission slot", reason)
        self.assertIn("--collect-only", reason)
        self.assertIn("<CI shard args>", reason)

    def test_flag_values_are_not_read_as_paths(self):
        # `-n auto` and `-k expr` must not be mistaken for path operands,
        # and their presence must not hide the anchors either.
        command = _anchor_sweep() + " -n auto -k 'not slow' --tb=short"
        _, outcome = _eval(command)
        self.assertEqual(outcome, "denied")

    def test_bare_pytest_binary_is_matched(self):
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        _, outcome = _eval(f"pytest {anchors}")
        self.assertEqual(outcome, "denied")

    def test_suppression_token_is_audited_not_honored(self):
        command = _anchor_sweep() + "  # lint:no-raw-pytest-check"
        reason, outcome = _eval(command)
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn("does NOT unblock", reason)


class TestAdvisoryShape(unittest.TestCase):
    def test_single_directory_sweep_advises(self):
        reason, outcome = _eval("python3 -m pytest runtime/api/domain/")
        self.assertEqual(outcome, "warn")
        self.assertIn("[advisory]", reason)
        self.assertIn("runtime/api/domain", reason)

    def test_pathless_run_sweeps_the_rootdir(self):
        reason, outcome = _eval("uv run --frozen python3 -m pytest -q")
        self.assertEqual(outcome, "warn")
        self.assertIn("the whole rootdir", reason)

    def test_a_directory_sweep_is_a_non_blocking_advisory(self):
        # Only the unambiguous whole-surface shape is deniable; a narrow
        # sweep may be a deliberate investigation.
        decision = lint.evaluate(
            lint._build_context_from_payload(_payload("pytest tests/"))
        )
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertFalse(decision.block)
        self.assertEqual(decision.message, "")
        self.assertEqual(guard_audit_outcome(decision), "warn")
        self.assertIn("[advisory]", decision.audit_fields["reason"])


    def test_suppressed_directory_sweep_stays_an_advisory_recording_the_attempt(self):
        command = "pytest tests/  # lint:no-raw-pytest-check"
        reason, outcome = _eval(command)
        self.assertEqual(outcome, "suppression_attempted")
        self.assertIn("[advisory]", reason)
        decision = lint.evaluate(lint._build_context_from_payload(_payload(command)))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertFalse(decision.block)
        self.assertEqual(decision.message, "")
        self.assertEqual(guard_audit_outcome(decision), "suppression_attempted")


class TestSilentShapes(unittest.TestCase):
    def test_file_scoped_run_is_not_matched(self):
        self.assertIsNone(
            _eval("python3 -m pytest runtime/api/domain/test_thing.py -k foo")
        )

    def test_watcher_wrapper_is_not_matched(self):
        self.assertIsNone(
            _eval(
                _anchor_sweep().replace(
                    "python3 -m pytest", "python3 -m yoke_core.tools.watch_pytest --"
                )
            )
        )

    def test_yoke_watch_spelling_is_not_matched(self):
        self.assertIsNone(
            _eval("yoke watch pytest -- runtime/api/ runtime/harness/ tests/")
        )

    def test_wrapped_collect_only_shard_is_not_matched(self):
        self.assertIsNone(
            _eval(
                "yoke watch pytest -- runtime/api/ runtime/harness/ tests/ "
                "--splits 4 --group 4 --collect-only -q"
            )
        )

    def test_qa_case_run_is_not_matched(self):
        self.assertIsNone(_eval("yoke qa case run --requirement-id 7"))

    def test_non_bash_tool_is_not_matched(self):
        payload = _payload(_anchor_sweep())
        payload["tool_name"] = "Read"
        decision = lint.evaluate(lint._build_context_from_payload(payload))
        self.assertIs(decision.outcome, Outcome.NOOP)


class TestRedirectionIsNotAPath(unittest.TestCase):
    """Capture-first redirection ends the operands; it is not one.

    The observed shape: twelve advisories in one session, every one
    naming ``2>&1`` or ``>"$_tmp" 2>&1`` as the swept path, because any
    non-flag token counted as an operand. Capture-first is the command
    shape this project's own rules prescribe, so the guard was firing on
    narrow runs that had done exactly the right thing.
    """

    def test_captured_file_scoped_run_is_not_matched(self):
        self.assertIsNone(
            _eval(
                "uv run --frozen python3 -m pytest runtime/api/test_a.py "
                'runtime/api/test_b.py >"$_tmp" 2>&1'
            )
        )

    def test_every_redirection_spelling_ends_the_operands(self):
        for suffix in (
            '>"$_tmp" 2>&1',
            "2>&1",
            "> out.log",
            ">> out.log",
            "&> both.log",
            "< in.txt",
        ):
            with self.subTest(suffix=suffix):
                self.assertIsNone(
                    _eval(f"python3 -m pytest runtime/api/test_a.py {suffix}")
                )

    def test_a_captured_directory_sweep_still_advises(self):
        verdict = _eval('python3 -m pytest runtime/api/ >"$_tmp" 2>&1')
        assert verdict is not None
        reason, _outcome = verdict
        self.assertIn("runtime/api", reason)
        self.assertNotIn("2>&1", reason)

    def test_a_captured_pathless_run_is_still_a_rootdir_sweep(self):
        verdict = _eval('python3 -m pytest -q >"$_tmp" 2>&1')
        assert verdict is not None
        self.assertIn("the whole rootdir", verdict[0])


class TestNonPytestCommandsNamingTestFiles(unittest.TestCase):
    """A test path in a command that never invokes pytest is not a sweep."""

    def test_heredoc_authoring_a_test_file(self):
        self.assertIsNone(
            _eval(
                "cat > runtime/api/test_new_thing.py <<'PY'\n"
                "import pytest\n"
                "def test_x():\n"
                "    assert True\n"
                "PY"
            )
        )

    def test_git_mv_between_test_directories(self):
        self.assertIsNone(
            _eval("git mv runtime/api/test_a.py runtime/harness/test_a.py")
        )

    def test_python_heredoc_editing_a_test_file(self):
        self.assertIsNone(
            _eval(
                "python3 - <<'PY'\n"
                "import pathlib\n"
                "p = pathlib.Path('runtime/api/test_a.py')\n"
                "p.write_text(p.read_text().replace('a', 'b'))\n"
                "PY"
            )
        )


class TestWrittenDataIsNotAnInvocation(unittest.TestCase):
    """Writing a pytest command string as data is not running it.

    Each shape was observed denying real QA plan-case authoring, whose
    ``method_config.command`` field legitimately stores a project test
    command as a JSON string value — inert text, never executed here.
    """

    def _anchor_command_field(self, joiner: str) -> str:
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        return (
            '{"method_config": {"command": "cd /repo '
            + joiner
            + " .venv/bin/python3 -m pytest "
            + anchors
            + ' -k \\"not live\\""}}'
        )

    def test_cat_heredoc_writing_the_command_as_json_is_not_matched(self):
        command = (
            "cat > scratch.json <<'EOF'\n"
            + self._anchor_command_field("&&")
            + "\nEOF\n"
        )
        self.assertIsNone(_eval(command))

    def test_python_heredoc_printing_the_command_as_json_is_not_matched(self):
        command = (
            "python3 <<'PYEOF' > scratch.json\n"
            "import json\n"
            "print(json.dumps(" + self._anchor_command_field("&&") + "))\n"
            "PYEOF\n"
        )
        self.assertIsNone(_eval(command))

    def test_printf_redirect_of_the_command_as_json_is_not_matched(self):
        payload = self._anchor_command_field("&&").replace("'", "'\\''")
        command = "printf '%s' '" + payload + "' > scratch.json"
        self.assertIsNone(_eval(command))

    def test_a_real_chained_invocation_after_the_written_data_still_denies(self):
        # The exemption covers written data, not a real command that
        # follows it on the same line.
        command = (
            "cat > scratch.json <<'EOF'\n"
            + self._anchor_command_field("&&")
            + "\nEOF\n"
            + _anchor_sweep()
        )
        _, outcome = _eval(command)
        self.assertEqual(outcome, "denied")


class TestDecisionEnvelope(unittest.TestCase):
    def test_deny_stops_the_chain_with_a_permission_envelope(self):
        decision = lint.evaluate(
            lint._build_context_from_payload(_payload(_anchor_sweep()))
        )
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertIs(decision.next, Next.STOP)
        self.assertIn("BLOCKED:", decision.message)
        self.assertEqual(guard_audit_outcome(decision), "denied")

    def test_clean_command_continues(self):
        decision = lint.evaluate(
            lint._build_context_from_payload(_payload("git status --short"))
        )
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)


if __name__ == "__main__":
    unittest.main()
