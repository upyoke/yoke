"""Resync utility tests: body normalization, label helpers, DriftRecord.

Stage-2 comparison tests live in test_resync_full_compare_text.py and
test_resync_full_compare_state.py. Doctor-format tests live in
test_resync_full_format.py. CLI tests live in test_resync_full_cli.py.

Pytest fixtures (test_db, populated_db) are shared via
_resync_full_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.resync import (
    DriftRecord,
    _get_label_value,
    _trim_trailing,
    normalize_body_for_compare,
)


class TestNormalizeBody:
    def test_empty_string(self):
        assert normalize_body_for_compare("") == ""

    def test_none(self):
        assert normalize_body_for_compare(None) == ""

    def test_trailing_whitespace(self):
        assert normalize_body_for_compare("hello  \n  ") == "hello"

    def test_backslash_collapse(self):
        assert normalize_body_for_compare("a\\\\b") == "a\x08"

    def test_escape_newline(self):
        result = normalize_body_for_compare("line1\\nline2")
        assert result == "line1\nline2"

    def test_escape_tab(self):
        result = normalize_body_for_compare("a\\tb")
        assert result == "a\tb"

    def test_escape_return(self):
        result = normalize_body_for_compare("a\\rb")
        assert result == "a\rb"

    def test_trailing_lines_after_expansion(self):
        result = normalize_body_for_compare("text\\n\\n\\n")
        assert result == "text"

    def test_complex_escapes(self):
        """Multiple escape types in one string."""
        result = normalize_body_for_compare("line1\\nline2\\ttab")
        assert result == "line1\nline2\ttab"

    def test_only_whitespace(self):
        assert normalize_body_for_compare("  \n\n  ") == ""

    def test_multiline_body(self):
        body = "# Title\n\nParagraph one.\n\nParagraph two."
        assert normalize_body_for_compare(body) == body.rstrip()


class TestTrimTrailing:
    def test_empty(self):
        assert _trim_trailing("") == ""

    def test_trailing_newlines(self):
        assert _trim_trailing("hello\n\n\n") == "hello"

    def test_trailing_spaces_on_lines(self):
        assert _trim_trailing("hello   \nworld   ") == "hello\nworld"


class TestGetLabelValue:
    def test_found(self):
        labels = [{"name": "status:active"}, {"name": "type:issue"}]
        assert _get_label_value(labels, "status:") == "active"

    def test_not_found(self):
        labels = [{"name": "type:issue"}]
        assert _get_label_value(labels, "status:") == ""

    def test_empty_labels(self):
        assert _get_label_value([], "status:") == ""

    def test_multiple_matching_returns_first(self):
        labels = [{"name": "status:active"}, {"name": "status:done"}]
        assert _get_label_value(labels, "status:") == "active"

    def test_prefix_not_found(self):
        labels = [{"name": "priority:high"}]
        assert _get_label_value(labels, "type:") == ""


class TestDriftRecord:
    def test_to_pipe(self):
        d = DriftRecord("YOK-42", "title", "local", "github")
        assert d.to_pipe() == "YOK-42|title|local|github"

    def test_to_pipe_with_special_chars(self):
        d = DriftRecord("YOK-1", "body", "<local body>", "<github body>")
        result = d.to_pipe()
        assert "YOK-1|body|" in result
