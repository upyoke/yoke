"""Tests for yoke_core.domain.lint_raw_pytest_full_suite_shell.

Covers the two preprocessing passes in isolation: interpreter-scoped
heredoc-body removal and data-sink-scoped quoted-span masking.
Integration coverage against the evidenced false-positive shapes and
the pre-existing executable-chain coverage they must not narrow lives
in test_lint_raw_pytest_full_suite.py.
"""

from __future__ import annotations

import unittest

from yoke_core.domain import lint_raw_pytest_full_suite_shell as shell


class TestMaskQuotedSpans(unittest.TestCase):
    def test_double_quoted_interior_is_blanked(self):
        self.assertEqual(shell.mask_quoted_spans('cmd "a && pytest b"'), 'cmd ""')

    def test_single_quoted_interior_is_blanked(self):
        self.assertEqual(shell.mask_quoted_spans("cmd 'not slow'"), "cmd ''")

    def test_escaped_double_quote_does_not_close_the_span(self):
        text = 'cmd "outer \\"inner\\" tail"'
        self.assertEqual(shell.mask_quoted_spans(text), 'cmd ""')

    def test_unquoted_text_is_unchanged(self):
        self.assertEqual(
            shell.mask_quoted_spans("python3 -m pytest tests/"),
            "python3 -m pytest tests/",
        )

    def test_backslash_inside_single_quotes_has_no_escape_meaning(self):
        # Real shell: single quotes have no escapes; the backslash is a
        # literal char and is masked along with everything else.
        self.assertEqual(shell.mask_quoted_spans("cmd 'a\\'"), "cmd ''")


class TestMaskDataSinkLines(unittest.TestCase):
    def test_printf_redirected_to_a_file_is_masked(self):
        line = "printf '%s' '{\"cmd\": \"pytest tests/\"}' > out.json"
        masked = shell.mask_data_sink_lines(line)
        self.assertNotIn("pytest", masked)
        self.assertIn("printf", masked)

    def test_printf_with_no_redirect_is_left_untouched(self):
        line = "printf '%s' 'pytest tests/'"
        self.assertEqual(shell.mask_data_sink_lines(line), line)

    def test_non_sink_program_is_left_untouched(self):
        # A `bash -c "... pytest ..."` line is not a data-writing sink,
        # even though it too has a quoted argument.
        line = 'bash -c "cd /repo && pytest tests/" > out.log'
        self.assertEqual(shell.mask_data_sink_lines(line), line)

    def test_echo_and_tee_are_recognized_sinks(self):
        for program in ("echo", "tee"):
            with self.subTest(program=program):
                line = f"{program} 'pytest tests/' > out.log"
                self.assertNotIn("pytest", shell.mask_data_sink_lines(line))

    def test_only_the_qualifying_line_in_a_multiline_command_is_masked(self):
        command = (
            "printf '%s' 'pytest tests/' > out.json\n"
            "bash -c 'pytest tests/'"
        )
        masked = shell.mask_data_sink_lines(command)
        lines = masked.split("\n")
        self.assertNotIn("pytest", lines[0])
        self.assertIn("pytest", lines[1])


class TestStripHeredocBodies(unittest.TestCase):
    def test_body_read_by_cat_is_removed_but_launch_line_survives(self):
        command = "cat > out.json <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertIn("cat > out.json <<'EOF'", stripped)
        self.assertNotIn("pytest", stripped)

    def test_body_read_by_bash_is_left_scannable(self):
        command = "bash <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_body_read_by_sh_is_left_scannable(self):
        command = "sh <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_text_after_the_terminator_is_preserved(self):
        command = "cat <<EOF\nbody\nEOF\necho done\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertIn("echo done", stripped)
        self.assertNotIn("body", stripped)

    def test_dash_variant_strips_leading_tabs_on_terminator(self):
        command = "cat <<-EOF\n\tpytest tests/\n\tEOF\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertNotIn("pytest", stripped)

    def test_here_string_is_left_untouched(self):
        command = "python3 -m pytest <<< 'not a body'"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_unterminated_heredoc_discards_the_remainder(self):
        command = "cat <<EOF\npytest tests/ runtime/api/"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertNotIn("pytest", stripped)

    def test_operator_inside_a_quoted_string_is_not_a_heredoc(self):
        command = 'grep -n "python3 - <<" file.py'
        self.assertEqual(shell.strip_heredoc_bodies(command), command)

    def test_no_heredoc_is_a_no_op(self):
        command = "python3 -m pytest tests/ runtime/api/"
        self.assertEqual(shell.strip_heredoc_bodies(command), command)


if __name__ == "__main__":
    unittest.main()
