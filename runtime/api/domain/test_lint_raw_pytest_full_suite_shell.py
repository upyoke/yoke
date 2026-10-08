"""Heredoc scope and executable nested shell coverage for raw pytest admission."""

from __future__ import annotations

import unittest

from yoke_core.domain import lint_raw_pytest_full_suite_shell as shell
from runtime.api.domain.test_lint_raw_pytest_full_suite import (
    _anchor_sweep,
    _eval,
    lint,
)


class TestStripHeredocBodies(unittest.TestCase):
    def test_body_read_by_cat_is_removed_but_launch_line_survives(self):
        command = "cat > out.json <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertIn("cat > out.json <<'EOF'", stripped)
        self.assertNotIn("pytest", stripped)

    def test_body_read_by_bash_is_left_scannable(self):
        # A redirect is present, but bash is not in the positive reader
        # admit list: it executes its heredoc body as commands.
        command = "bash > out.log <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_body_read_by_sh_is_left_scannable(self):
        command = "sh > out.log <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_text_after_the_terminator_is_preserved(self):
        command = "cat > out.txt <<EOF\nbody\nEOF\necho done\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertIn("echo done", stripped)
        self.assertNotIn("body", stripped)

    def test_dash_variant_strips_leading_tabs_on_terminator(self):
        command = "cat > out.txt <<-EOF\n\tpytest tests/\n\tEOF\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertNotIn("pytest", stripped)

    def test_here_string_is_left_untouched(self):
        command = "python3 -m pytest <<< 'not a body'"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_unterminated_heredoc_discards_the_remainder(self):
        command = "cat > out.txt <<EOF\npytest tests/ runtime/api/"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertNotIn("pytest", stripped)

    def test_known_data_reader_needs_no_output_redirect(self):
        # Printing text is still data, provided no pipe feeds it to a shell.
        command = "cat <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertNotIn("pytest", shell.strip_heredoc_bodies(command))

    def test_heredoc_piped_into_another_program_is_left_scannable(self):
        # `cat` reads the heredoc, but its output feeds `bash`, which
        # executes it -- no redirect on the launch line either.
        command = "cat <<'EOF' | bash\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_launcher_wrapped_shell_heredoc_is_left_scannable(self):
        # `env` forwards to `bash`; the reading-program admit list
        # excludes "env" regardless of the redirect gate.
        command = "env bash <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_launcher_wrapped_shell_heredoc_with_redirect_is_left_scannable(self):
        # A redirect alone is not proof of an inert reader: `env` still
        # forwards to `bash`, which executes the heredoc body.
        command = "env bash > out.log <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_operator_inside_a_quoted_string_is_not_a_heredoc(self):
        command = 'grep -n "python3 - <<" file.py'
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_no_heredoc_is_a_no_op(self):
        command = "python3 -m pytest tests/ runtime/api/"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)


class TestExecutableShellCoverage(unittest.TestCase):
    """Executable shell payloads retain admission coverage."""

    def test_bash_heredoc_running_a_real_sweep_still_denies(self):
        command = (
            "bash <<'EOF'\npytest "
            + " ".join(f"{a}/" for a in lint.full_sweep_anchors())
            + "\nEOF\n"
        )
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_sh_heredoc_running_a_real_sweep_still_denies(self):
        command = (
            "sh <<'EOF'\npytest "
            + " ".join(f"{a}/" for a in lint.full_sweep_anchors())
            + "\nEOF\n"
        )
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_shell_dash_c_chained_pytest_is_still_flagged(self):
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        command = 'bash -c "cd /repo && python3 -m pytest ' + anchors + '"'
        self.assertIsNotNone(_eval(command))


class TestNestedExecution(unittest.TestCase):
    def test_comments_are_inert_and_split_string_launcher_is_executable(self):
        source = "pytest " + " ".join(lint.full_sweep_anchors())
        for command in (
            f"echo ok # ; {source}",
            f"echo ok # $({source})",
            f"echo '{source}' # | bash",
            f"echo '{source}' & rg harmless file | bash",
        ):
            self.assertIsNone(_eval(command))
        self.assertEqual(_eval(f"env -S '{source}'")[0], "deny")
        self.assertEqual(_eval(f"echo ok # ignored\n{source}")[0], "deny")

    def test_minimized_recent_search_and_content_payloads(self):
        for command in (
            "rg -n 'lint|ruff|pytest|uv run' config | head -20",
            "rg --files workflows | rg '(selection|pytest|verification)'",
            "ps -axo pid,ppid,command | rg 'watch_pytest|pytest -n 4 tests|pid'",
            "grep -i -E 'xdist|admission|pytest worker|capacity' capture",
            "python3 - <<'EOF'\nprint('a|pytest|b')\nEOF",
            "yoke items progress-log append TEST-1 --stdin <<'EOF'\npytest reported success.\nEOF",
        ):
            self.assertIsNone(_eval(command))
        # The entire payload matters: a test after an inert body still runs.
        self.assertIsNotNone(
            _eval(
                "python3 - <<'EOF'\nprint('a|pytest|b')\nEOF\n"
                "python3 -m pytest events -q > /tmp/capture 2>&1"
            )
        )

    def test_executable_sources_deny_but_single_quoted_data_stays_inert(self):
        anchors = " ".join(lint.full_sweep_anchors())
        source = "pytest " + anchors
        for command in (
            f"bash -c '{source}'",
            f"env sh -ec '{source}'",
            f"eval '{source}'",
            f'echo "$({source})" > /tmp/out',
            f"echo $({source})",
            "echo " + chr(96) + source + chr(96),
            f"cat <({source})",
            f"yoke watch pytest -- -k '$({source})'; {source}",
            f'yoke watch pytest -- -k "$({source})"',
            f"printf '%s\\n' '{source}' | bash",
            f"echo 'cd /repo && {source}' | sh",
            f"bash <<< '{source}'",
            f"cat > /tmp/out <<EOF\n'$({source})'\nEOF",
        ):
            with self.subTest(command=command):
                self.assertEqual(_eval(command)[0], "deny")
        for command in (
            f"echo '$({source})'",
            f"cat > /tmp/out <<'EOF'\n$({source})\nEOF",
            f"printf '%s' '{source}' > /tmp/out",
        ):
            self.assertIsNone(_eval(command))

    def test_registered_content_heredocs_are_data(self):
        for writer in (
            "yoke items progress-log append TEST-1 --stdin",
            "yoke items structured-field replace TEST-1 --field test_results --stdin",
        ):
            self.assertIsNone(_eval(writer + " <<'EOF'\npytest reported success.\nEOF"))
            self.assertEqual(
                _eval(
                    writer
                    + " <<EOF\n$(pytest "
                    + " ".join(lint.full_sweep_anchors())
                    + ")\nEOF"
                )[0],
                "deny",
            )

    def test_unknown_or_malformed_execution_does_not_gain_admission(self):
        self.assertIsNotNone(_eval("bash -c 'pytest tests/"))
        self.assertIsNotNone(_eval("mystery <<'EOF'\npytest tests/\nEOF"))

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
        command = (
            "cat <<'EOF' | bash\npytest "
            + " ".join(f"{a}/" for a in lint.full_sweep_anchors())
            + "\nEOF\n"
        )
        mode, _, _ = _eval(command)
        self.assertEqual(mode, "deny")

    def test_sink_redirect_chained_with_an_executable_statement_is_untouched(self):
        # A data-sink-with-redirect statement chained (via `;`) with a
        # second, different, executable statement on the same physical
        # line must not have ITS quotes masked away by the first
        # statement's sink/redirect shape.
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        command = "echo ok > /tmp/x; bash -c 'cd /repo && pytest " + anchors + "'"
        self.assertIsNotNone(_eval(command))


class TestQuotedOperandsAndAdmission(unittest.TestCase):
    def test_real_search_patterns_do_not_invent_invocations(self):
        for pattern in (
            "timeout-minutes|pytest|run_tests|node|ruff",
            "failed|error|Error|warning|summary|pytest|exit|FAIL",
            "rebase;pytest;CI",
            "|",
            "pytest",
        ):
            with self.subTest(pattern=pattern):
                self.assertIsNone(_eval(f"rg -n '{pattern}' file"))

    def test_raw_invocation_after_data_or_wrapper_still_denies(self):
        for prefix in (
            "rg -n 'a|pytest|b' file",
            "echo 'yoke_core.tools.run_tests'",
            "printf '%s' 'yoke watch pytest'",
            "yoke watch pytest -- tests/test_small.py",
            "yoke qa case run --requirement-id 7",
        ):
            for operator in (";", "&&", "||", "|", "&", "\n"):
                with self.subTest(prefix=prefix, operator=operator):
                    self.assertEqual(
                        _eval(prefix + operator + _anchor_sweep())[0], "deny"
                    )

    def test_launchers_and_compounds_preserve_real_admission(self):
        for prefix in (
            "env -u NAME",
            "nice -n 5",
            "time -f '%e'",
            "command",
            "exec -a suite",
            "uv run --project /repo --frozen",
            "poetry run",
            "pdm run",
            "rye run",
            "hatch -e test run",
            "yoke dev run --",
            "if",
            "then",
            "(",
        ):
            with self.subTest(prefix=prefix):
                self.assertEqual(_eval(prefix + " " + _anchor_sweep())[0], "deny")

    def test_python_script_argument_is_not_a_module_invocation(self):
        for command in (
            "python3 script.py -m pytest tests/",
            "python3 -c 'print(1)' -m pytest tests/",
            "python3 -m tool -m pytest tests/",
        ):
            self.assertIsNone(_eval(command))

    def test_later_full_invocation_wins_over_earlier_advisory(self):
        self.assertEqual(_eval("pytest tests/; " + _anchor_sweep())[0], "deny")


if __name__ == "__main__":
    unittest.main()
