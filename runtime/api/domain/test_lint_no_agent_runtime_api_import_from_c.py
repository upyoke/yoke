"""Tests for yoke_core.domain.lint_no_agent_runtime_api_import_from_c.

Covers the four canonical contracts:

- Positive trip: ``python3 -c "from runtime..."`` denies.
- False-positive guards: stdlib imports, ``-m`` invocations, unrelated scripts.
- Suppression token is audit-only — the rule still denies in deny mode.
- Warn mode emits a WARN decision, not a deny envelope.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from yoke_core.domain import lint_no_agent_runtime_api_import_from_c as lint
from yoke_core.hooks.types import Next, Outcome


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


def _record_for(payload: dict):
    return lint._build_context_from_payload(payload)


def _eval(command: str, *, mode: str = "deny"):
    with mock.patch.object(lint, "_read_mode", return_value=mode):
        return lint.evaluate_payload(_payload(command))


class TestPositiveTrip(unittest.TestCase):
    """``python3 -c "from runtime..."`` shapes that must deny."""

    def test_basic_runtime_api_import_denies(self):
        cmd = (
            'python3 -c "from yoke_core.domain.yoke_function_dispatch '
            'import dispatch; print(dispatch)"'
        )
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(mode, "deny")
        self.assertEqual(outcome, "denied")
        self.assertIn("BLOCKED", reason)

    def test_message_clarifies_dash_m_is_not_blocked(self):
        # The denial message must state it targets only `-c` one-liners so
        # agents do not read it as banning the sanctioned `-m` bootstrap.
        cmd = 'python3 -c "from yoke_core.domain.events import emit"'
        result = _eval(cmd)
        self.assertIsNotNone(result)
        _mode, reason, _outcome = result
        self.assertIn("-m", reason)
        self.assertIn("module invocations", reason)

    def test_runtime_harness_import_denies(self):
        cmd = 'python3 -c "from yoke_core.hooks.sessions_cli import x"'
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_split_package_imports_deny(self):
        for package in ("yoke_cli", "yoke_harness"):
            with self.subTest(package=package):
                cmd = f'python3 -c "import {package}; print({package})"'
                result = _eval(cmd)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result[0], "deny")

    def test_bare_import_runtime_denies(self):
        cmd = "python3 -c \"import yoke_core.domain.session; print('ok')\""
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_python_unversioned_denies(self):
        cmd = 'python -c "from yoke_core.domain.events import emit"'
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")

    def test_chained_invocation_denies(self):
        cmd = 'git status && python3 -c "from yoke_core.domain.events import emit"'
        result = _eval(cmd)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "deny")


class TestFalsePositiveGuards(unittest.TestCase):
    """Allowed shapes that must NOT trigger the deny."""

    def test_stdlib_import_allowed(self):
        self.assertIsNone(_eval('python3 -c "import json; print(json.dumps({}))"'))

    def test_collections_import_allowed(self):
        self.assertIsNone(
            _eval(
                'python3 -c "from collections import defaultdict; print(defaultdict)"'
            )
        )

    def test_module_invocation_allowed(self):
        # ``-m`` form is the canonical CLI adapter shape — must not trip.
        self.assertIsNone(
            _eval("python3 -m yoke_core.cli.db_router items get YOK-1 status")
        )
        self.assertIsNone(
            _eval("python3 -m yoke_core.api.service_client claim-work --item YOK-1")
        )

    def test_script_file_invocation_allowed(self):
        # File path invocation, not -c form.
        self.assertIsNone(_eval("python3 /tmp/script.py"))
        self.assertIsNone(_eval("python3 runtime/api/tools/foo.py"))

    def test_claimed_lane_source_runner_owns_direct_imports(self):
        self.assertIsNone(
            _eval('yoke dev run -- python3 -c "import runtime,yoke_core"')
        )

    def test_source_runner_allows_required_session_export_prefix(self):
        self.assertIsNone(
            _eval(
                "export YOKE_SESSION_ID=session-1\n"
                'yoke dev run -- python3 -c "import runtime,yoke_core"'
            )
        )

    def test_source_runner_does_not_hide_an_unrelated_prefix_command(self):
        result = _eval(
            'python3 -c "from yoke_core.domain.events import emit"\n'
            'yoke dev run -- python3 -c "import runtime,yoke_core"'
        )
        self.assertIsNotNone(result)

    def test_unrelated_command_allowed(self):
        self.assertIsNone(_eval("git status"))
        self.assertIsNone(_eval("ls -la /tmp"))

    def test_runtime_string_in_unrelated_context_allowed(self):
        # The substring 'runtime' in echo or comments must not trip.
        self.assertIsNone(_eval('echo "runtime imports are not allowed"'))
        self.assertIsNone(_eval("python3 -c \"print('runtime.api is a string here')\""))

    def test_non_bash_tool_no_deny(self):
        result = lint.evaluate_payload(
            {
                "tool_name": "Read",
                "tool_input": {"command": 'python3 -c "from runtime.api import x"'},
            }
        )
        self.assertIsNone(result)

    def test_empty_command_no_deny(self):
        self.assertIsNone(_eval(""))


class TestSuppressionTokenAudit(unittest.TestCase):
    """Suppression token is recorded as audit evidence but does NOT unblock."""

    def test_token_records_attempt_still_denies(self):
        cmd = (
            'python3 -c "from yoke_core.domain.events import emit"  '
            "# lint:no-agent-runtime-import-check"
        )
        result = _eval(cmd)
        self.assertIsNotNone(result)
        mode, reason, outcome = result
        self.assertEqual(outcome, "suppression_attempted")
        self.assertEqual(mode, "deny")
        self.assertIn("does NOT unblock", reason)

    def test_evaluate_still_denies_with_attempted_outcome(self):
        cmd = (
            'python3 -c "from yoke_core.domain.events import emit"  '
            "# lint:no-agent-runtime-import-check"
        )
        with (
            mock.patch.object(lint, "_read_mode", return_value="deny"),
            mock.patch.object(lint, "_emit_audit_event") as emit_mock,
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertEqual(emit_mock.call_args.args[3], "suppression_attempted")


class TestModePin(unittest.TestCase):
    def test_warn_mode_returns_warn_no_deny_envelope(self):
        cmd = 'python3 -c "from yoke_core.domain.events import emit"'
        with (
            mock.patch.object(lint, "_read_mode", return_value="warn"),
            mock.patch.object(lint, "_emit_audit_event"),
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.WARN)
        self.assertEqual(decision.message, "")
        self.assertFalse(decision.block)
        self.assertIs(decision.next, Next.CONTINUE)

    def test_deny_mode_emits_envelope(self):
        cmd = 'python3 -c "from yoke_core.domain.events import emit"'
        with (
            mock.patch.object(lint, "_read_mode", return_value="deny"),
            mock.patch.object(lint, "_emit_audit_event"),
        ):
            decision = lint.evaluate(_record_for(_payload(cmd)))
        self.assertIs(decision.outcome, Outcome.DENY)
        self.assertTrue(decision.block)
        self.assertIs(decision.next, Next.STOP)
        envelope = json.loads(decision.message)
        self.assertEqual(envelope["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "BLOCKED", envelope["hookSpecificOutput"]["permissionDecisionReason"]
        )


class TestFailOpen(unittest.TestCase):
    def test_invalid_payload_returns_noop(self):
        decision = lint.evaluate(_record_for({}))
        self.assertIs(decision.outcome, Outcome.NOOP)
        self.assertIs(decision.next, Next.CONTINUE)
        self.assertFalse(decision.block)

    def test_malformed_quoting_no_crash(self):
        # shlex.split raises ValueError on unbalanced quotes — fail open.
        self.assertIsNone(_eval('python3 -c "from runtime'))


class TestRegisteredSourceRunWrapper(unittest.TestCase):
    """``yoke dev run -- <command>`` is the mandated shape for lane source.

    The exemption has to follow the invocation the ``-c`` body belongs to.
    Deciding it from the command's LINES instead recognised only a
    single-line invocation, so the same wrapper was refused whenever its
    body spanned lines or another command ran ahead of it.
    """

    # Denied on its own, so each test below proves the wrapper is what
    # exempts it rather than the body being innocuous.
    ONE_LINE_BODY = '"import yoke_core, yoke_contracts"'
    MULTI_LINE_BODY = (
        '"\n'
        "import yoke_core.domain.qa_admitted_case_currency as c\n"
        "print('imports ok', c.STALE_PLAN_CASE_CODE)\n"
        '"'
    )

    def assert_wrapper_decides(self, prefix: str, body: str) -> None:
        self.assertIsNotNone(
            _eval(f"{prefix}python3 -c {body}"),
            "fixture proves nothing unless the unwrapped form denies",
        )
        self.assertIsNone(_eval(f"{prefix}yoke dev run -- python3 -c {body}"))

    def test_wrapped_one_line_body_is_exempt(self):
        self.assert_wrapper_decides("", self.ONE_LINE_BODY)

    def test_wrapped_multi_line_body_is_exempt(self):
        self.assert_wrapper_decides("", self.MULTI_LINE_BODY)

    def test_wrapped_invocation_after_another_command_is_exempt(self):
        self.assert_wrapper_decides(
            "cd /Users/me/.worktrees/LANE && ", self.MULTI_LINE_BODY
        )

    def test_wrapped_invocation_after_an_env_assignment_is_exempt(self):
        self.assert_wrapper_decides("YOKE_ENV=prod-db-admin ", self.ONE_LINE_BODY)

    def test_an_unwrapped_invocation_beside_a_wrapped_one_still_denies(self):
        verdict = _eval(
            'yoke dev run -- python3 -c "import yoke_core, yoke_contracts"'
            " && python3 -c \"import yoke_core, yoke_harness\""
        )
        self.assertIsNotNone(verdict)

    def test_a_bare_interpreter_path_is_not_the_wrapper(self):
        self.assertIsNotNone(
            _eval(
                '/Users/me/yoke/.venv/bin/python3 -c "import yoke_core, yoke_contracts"'
            )
        )


class TestDenialNamesWhatItMatched(unittest.TestCase):
    """A compound command gives the reader no way to tell which half matched.

    One field-note attributed a correct denial to a heredoc that was only
    editing a file, because the refusal named the rule and nothing else. The
    reason has to quote the import it actually matched.
    """

    HEREDOC_EDIT_THEN_REACH_IN = (
        "python3 - <<'PYEOF'\n"
        "import pathlib\n"
        'p = pathlib.Path("packages/yoke-core/src/yoke_core/domain/surfaces.py")\n'
        'new = "from yoke_core.domain.item_worktrees import list_item_worktrees"\n'
        'p.write_text(p.read_text().replace("# anchor", new))\n'
        "PYEOF\n"
        'python3 -c "from yoke_core.domain.surfaces import render"'
    )

    def test_a_file_editing_heredoc_alone_is_not_an_import(self):
        heredoc_only = self.HEREDOC_EDIT_THEN_REACH_IN.rsplit("\n", 1)[0]
        self.assertIsNone(_eval(heredoc_only))

    def test_the_matched_import_is_quoted_in_the_reason(self):
        verdict = _eval(self.HEREDOC_EDIT_THEN_REACH_IN)
        self.assertIsNotNone(verdict)
        reason = verdict[1]
        self.assertIn("from yoke_core.domain.surfaces import render", reason)
        self.assertNotIn("list_item_worktrees", reason)

    def test_the_reason_locates_which_invocation_matched(self):
        # Same reach-in, different position: the refusal has to move with it,
        # or a compound command still leaves the reader guessing which
        # segment to look at.
        reach_in = 'python3 -c "from yoke_core.domain.surfaces import render"'
        alone = _eval(reach_in)
        after_a_heredoc = _eval(self.HEREDOC_EDIT_THEN_REACH_IN)
        self.assertIsNotNone(alone)
        self.assertIsNotNone(after_a_heredoc)
        self.assertNotEqual(
            alone[1],
            after_a_heredoc[1],
            "the reason must distinguish the invocation it matched",
        )


if __name__ == "__main__":
    unittest.main()
