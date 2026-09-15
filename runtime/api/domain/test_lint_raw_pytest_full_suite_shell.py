"""Tests for yoke_core.domain.lint_raw_pytest_full_suite_shell.

Covers the two preprocessing passes in isolation: heredoc-body removal
and quoted-span interior masking. Integration coverage against the
actual FN50157 false-positive shapes lives in
test_lint_raw_pytest_full_suite.py.
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


class TestStripHeredocBodies(unittest.TestCase):
    def test_body_is_removed_but_launch_line_survives(self):
        command = "cat > out.json <<'EOF'\npytest tests/ runtime/api/\nEOF\n"
        stripped = shell.strip_heredoc_bodies(command)
        self.assertIn("cat > out.json <<'EOF'", stripped)
        self.assertNotIn("pytest", stripped)

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
