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
        self.assertIn("--collect-only", reason)
        self.assertIn("<CI shard args>", reason)

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

    def test_wrapped_collect_only_shard_is_not_matched(self):
        self.assertIsNone(_eval(
            "yoke watch pytest -- runtime/api/ runtime/harness/ tests/ "
            "--splits 4 --group 4 --collect-only -q"
        ))

    def test_qa_case_run_is_not_matched(self):
        self.assertIsNone(_eval("yoke qa case run --requirement-id 7"))

    def test_non_bash_tool_is_not_matched(self):
        payload = _payload(_anchor_sweep())
        payload["tool_name"] = "Read"
        self.assertIsNone(lint.evaluate_payload(payload))


class TestRedirectionIsNotAPath(unittest.TestCase):
    """Capture-first redirection ends the operands; it is not one.

    The observed shape: twelve advisories in one session, every one
    naming ``2>&1`` or ``>"$_tmp" 2>&1`` as the swept path, because any
    non-flag token counted as an operand. Capture-first is the command
    shape this project's own rules prescribe, so the guard was firing on
    narrow runs that had done exactly the right thing.
    """

    def test_captured_file_scoped_run_is_not_matched(self):
        self.assertIsNone(_eval(
            'uv run --frozen python3 -m pytest runtime/api/test_a.py '
            'runtime/api/test_b.py >"$_tmp" 2>&1'
        ))

    def test_every_redirection_spelling_ends_the_operands(self):
        for suffix in ('>"$_tmp" 2>&1', "2>&1", "> out.log", ">> out.log",
                       "&> both.log", "< in.txt"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(
                    _eval(f"python3 -m pytest runtime/api/test_a.py {suffix}")
                )

    def test_a_captured_directory_sweep_still_advises(self):
        verdict = _eval('python3 -m pytest runtime/api/ >"$_tmp" 2>&1')
        assert verdict is not None
        _mode, reason, _outcome = verdict
        self.assertIn("runtime/api", reason)
        self.assertNotIn("2>&1", reason)

    def test_a_captured_pathless_run_is_still_a_rootdir_sweep(self):
        verdict = _eval('python3 -m pytest -q >"$_tmp" 2>&1')
        assert verdict is not None
        self.assertIn("the whole rootdir", verdict[1])


class TestNonPytestCommandsNamingTestFiles(unittest.TestCase):
    """A test path in a command that never invokes pytest is not a sweep."""

    def test_heredoc_authoring_a_test_file(self):
        self.assertIsNone(_eval(
            "cat > runtime/api/test_new_thing.py <<'PY'\n"
            "import pytest\n"
            "def test_x():\n"
            "    assert True\n"
            "PY"
        ))

    def test_git_mv_between_test_directories(self):
        self.assertIsNone(_eval(
            "git mv runtime/api/test_a.py runtime/harness/test_a.py"
        ))

    def test_python_heredoc_editing_a_test_file(self):
        self.assertIsNone(_eval(
            "python3 - <<'PY'\n"
            "import pathlib\n"
            "p = pathlib.Path('runtime/api/test_a.py')\n"
            "p.write_text(p.read_text().replace('a', 'b'))\n"
            "PY"
        ))


class TestWrittenDataIsNotAnInvocation(unittest.TestCase):
    """Writing a pytest command string as data is not running it.

    Each shape was observed denying real QA plan-case authoring, whose
    ``method_config.command`` field legitimately stores a project test
    command as a JSON string value — inert text, never executed here.
    """

    def _anchor_command_field(self, joiner: str) -> str:
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        return (
            '{"method_config": {"command": "cd /repo ' + joiner +
            ' .venv/bin/python3 -m pytest ' + anchors + ' -k \\"not live\\""}}'
        )

    def test_cat_heredoc_writing_the_command_as_json_is_not_matched(self):
        command = (
            "cat > scratch.json <<'EOF'\n"
            + self._anchor_command_field("&&") + "\nEOF\n"
        )
        self.assertIsNone(_eval(command))

    def test_python_heredoc_printing_the_command_as_json_is_not_matched(self):
        command = (
            "python3 <<'PYEOF' > scratch.json\n"
            "import json\n"
            'print(json.dumps(' + self._anchor_command_field("&&") + '))\n'
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
            + self._anchor_command_field("&&") + "\nEOF\n"
            + _anchor_sweep()
        )
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")


class TestExecutableCoverageIsUnchanged(unittest.TestCase):
    """Baseline-vs-candidate parity: exempting written data must not
    narrow the coverage this guard already had for a genuinely
    executable chain, however that coverage arose.

    A heredoc read by a shell interpreter is executed as commands line
    by line, unlike one read by ``cat``/``python3``; a shell's own
    ``-c`` argument was already only accidentally caught (naive,
    quote-oblivious splitting exposed a separator inside it), and stays
    exactly as accidental — this locks in that pre-existing shape
    rather than either fixing or losing it.
    """

    def test_bash_heredoc_running_a_real_sweep_still_denies(self):
        command = "bash <<'EOF'\npytest " + " ".join(
            f"{a}/" for a in lint.full_sweep_anchors()
        ) + "\nEOF\n"
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_sh_heredoc_running_a_real_sweep_still_denies(self):
        command = "sh <<'EOF'\npytest " + " ".join(
            f"{a}/" for a in lint.full_sweep_anchors()
        ) + "\nEOF\n"
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_shell_dash_c_chained_pytest_is_still_flagged(self):
        # Locks in the pre-existing (already-incomplete) behavior: this
        # shape was never a clean "full" deny — the naive split leaves a
        # trailing quote glued to the last anchor — so parity means
        # still non-None, not a newly-precise verdict.
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        command = 'bash -c "cd /repo && python3 -m pytest ' + anchors + '"'
        self.assertIsNotNone(_eval(command))

    def test_launcher_wrapped_shell_heredoc_still_denies(self):
        # A compound form: `env` only forwards to bash -- the body is
        # still executed line by line, with or without a redirect.
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        for launch in ("env bash <<'EOF'", "env bash > out.log <<'EOF'"):
            with self.subTest(launch=launch):
                command = f"{launch}\npytest {anchors}\nEOF\n"
                mode, _, _ = _eval(command)
                self.assertEqual(mode, "deny")

    def test_heredoc_piped_into_a_shell_still_denies(self):
        # Another compound form: the heredoc's own reader is `cat`, but
        # its output is piped into `bash`, which executes it.
        command = "cat <<'EOF' | bash\npytest " + " ".join(
            f"{a}/" for a in lint.full_sweep_anchors()
        ) + "\nEOF\n"
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_sink_redirect_chained_with_an_executable_statement_is_untouched(self):
        # A data-sink-with-redirect statement chained (via `;`) with a
        # second, different, executable statement on the same physical
        # line must not have ITS quotes masked away by the first
        # statement's sink/redirect shape.
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        command = (
            "echo ok > /tmp/x; bash -c 'cd /repo && pytest " + anchors + "'"
        )
        self.assertIsNotNone(_eval(command))


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
