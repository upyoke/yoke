"""Heredoc scope and executable nested shell coverage for raw pytest admission."""

from __future__ import annotations

import unittest

from runtime.api.domain.test_lint_raw_pytest_full_suite import (
    _anchor_sweep,
    _eval,
    lint,
)


def _sweep() -> str:
    return " ".join(f"{a}/" for a in lint.full_sweep_anchors())


class TestHeredocBodiesAreInput(unittest.TestCase):
    """A heredoc body is input; only a shell reading it runs it."""

    def test_body_read_by_a_data_reader_is_not_scanned(self):
        for launch, end in (
            ("cat > out.json <<'EOF'", "EOF"),
            ("cat <<'EOF'", "EOF"),
            ("cat > out.txt <<-EOF", "\tEOF"),
        ):
            with self.subTest(launch=launch):
                self.assertIsNone(_eval(f"{launch}\n\tpytest {_sweep()}\n{end}\n"))

    def test_text_after_the_terminator_is_still_a_command(self):
        command = f"cat > out.txt <<EOF\nbody\nEOF\npytest {_sweep()}\n"
        self.assertEqual(_eval(command)[1], "denied")

    def test_unterminated_heredoc_body_stays_input(self):
        self.assertIsNone(_eval(f"cat > out.txt <<EOF\npytest {_sweep()}"))

    def test_operator_inside_a_quoted_string_is_not_a_heredoc(self):
        self.assertIsNone(_eval('grep -n "python3 - <<" file.py'))

    def test_quoted_body_with_unbalanced_quotes_is_not_shell(self):
        # A typed item writer behind a global option, with prose that
        # names a sweep and leaves a quote open, is data, not a command.
        command = (
            "yoke --env prod items structured-field replace YOK-1 --field spec "
            "--stdin <<'EOF'\nDon't run pytest runtime/ tests/ by \"hand.\nEOF"
        )
        self.assertIsNone(_eval(command))

    def test_quoted_body_fed_to_an_unknown_reader_is_input(self):
        self.assertIsNone(_eval(f"mystery <<'EOF'\npytest {_sweep()}\nEOF"))

    def test_env_cleared_module_invocation_is_still_raw_pytest(self):
        self.assertEqual(_eval(f"env -i X=1 python3 -m pytest {_sweep()}")[1], "denied")


class TestExecutableShellCoverage(unittest.TestCase):
    """Executable shell payloads retain admission coverage."""

    def test_bash_heredoc_running_a_real_sweep_still_denies(self):
        command = (
            "bash <<'EOF'\npytest "
            + " ".join(f"{a}/" for a in lint.full_sweep_anchors())
            + "\nEOF\n"
        )
        _, outcome = _eval(command)
        self.assertEqual(outcome, "denied")

    def test_sh_heredoc_running_a_real_sweep_still_denies(self):
        command = (
            "sh <<'EOF'\npytest "
            + " ".join(f"{a}/" for a in lint.full_sweep_anchors())
            + "\nEOF\n"
        )
        _, outcome = _eval(command)
        self.assertEqual(outcome, "denied")

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
        self.assertEqual(_eval(f"env -S '{source}'")[1], "denied")
        self.assertEqual(_eval(f"echo ok # ignored\n{source}")[1], "denied")

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
                self.assertEqual(_eval(command)[1], "denied")
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
                )[1],
                "denied",
            )

    def test_unknown_or_malformed_execution_does_not_gain_admission(self):
        self.assertIsNotNone(_eval("bash -c 'pytest tests/"))

    def test_launcher_wrapped_shell_heredoc_still_denies(self):
        # A compound form: `env` only forwards to bash -- the body is
        # still executed line by line, with or without a redirect.
        anchors = " ".join(f"{a}/" for a in lint.full_sweep_anchors())
        for launch in ("env bash <<'EOF'", "env bash > out.log <<'EOF'"):
            with self.subTest(launch=launch):
                command = f"{launch}\npytest {anchors}\nEOF\n"
                _, outcome = _eval(command)
                self.assertEqual(outcome, "denied")

    def test_heredoc_piped_into_a_shell_still_denies(self):
        # Another compound form: the heredoc's own reader is `cat`, but
        # its output is piped into `bash`, which executes it.
        command = (
            "cat <<'EOF' | bash\npytest "
            + " ".join(f"{a}/" for a in lint.full_sweep_anchors())
            + "\nEOF\n"
        )
        _, outcome = _eval(command)
        self.assertEqual(outcome, "denied")

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
                        _eval(prefix + operator + _anchor_sweep())[1], "denied"
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
                self.assertEqual(_eval(prefix + " " + _anchor_sweep())[1], "denied")

    def test_python_script_argument_is_not_a_module_invocation(self):
        for command in (
            "python3 script.py -m pytest tests/",
            "python3 -c 'print(1)' -m pytest tests/",
            "python3 -m tool -m pytest tests/",
        ):
            self.assertIsNone(_eval(command))

    def test_later_full_invocation_wins_over_earlier_advisory(self):
        self.assertEqual(_eval("pytest tests/; " + _anchor_sweep())[1], "denied")


if __name__ == "__main__":
    unittest.main()
