"""Unit tests for the quote-aware pipeline splitter.

Targets AC-6 and AC-9: ``-separator "|"`` (quoted pipe) must
not produce an ambiguous pipeline; real pipelines still split; quoted
``;``, ``&&``, and ``||`` operators are literal; backslash escapes are
honoured.
"""

from __future__ import annotations

from yoke_core.domain.path_claim_bash_splitter import (
    has_unquoted_heredoc,
    split_pipeline,
)


def test_real_pipeline_splits():
    assert split_pipeline("a | b") == ["a", "b"]


def test_real_chain_splits_on_semicolon():
    assert split_pipeline("a ; b ; c") == ["a", "b", "c"]


def test_real_chain_splits_on_double_amp_and_double_pipe():
    assert split_pipeline("a && b || c") == ["a", "b", "c"]


def test_quoted_pipe_in_double_quotes_is_literal():
    cmd = 'db_router query -separator "|" "SELECT 1"'
    segments = split_pipeline(cmd)
    assert segments == [cmd]


def test_quoted_pipe_in_single_quotes_is_literal():
    cmd = "db_router query -separator '|' 'SELECT 1'"
    segments = split_pipeline(cmd)
    assert segments == [cmd]


def test_quoted_semicolon_is_literal():
    cmd = 'echo "a ; b ; c"'
    assert split_pipeline(cmd) == [cmd]


def test_quoted_double_amp_is_literal():
    cmd = 'echo "x && y"'
    assert split_pipeline(cmd) == [cmd]


def test_backslash_escaped_pipe_is_literal():
    cmd = "echo \\| not-a-pipe"
    assert split_pipeline(cmd) == [cmd]


def test_mixed_quote_and_unquoted_split():
    cmd = 'echo "a | b" | grep x'
    segments = split_pipeline(cmd)
    assert segments == ['echo "a | b"', "grep x"]


def test_empty_segments_dropped():
    assert split_pipeline(";; a ;;; b ;;") == ["a", "b"]


def test_double_quote_does_not_close_inside_single_quotes():
    cmd = "echo 'a \"b | c\" d'"
    assert split_pipeline(cmd) == [cmd]


def test_whitespace_around_segments_is_stripped():
    assert split_pipeline("  a   |   b  ") == ["a", "b"]


def test_empty_command_returns_empty_list():
    assert split_pipeline("") == []
    assert split_pipeline("   ") == []


def test_trailing_operator_is_silently_dropped():
    assert split_pipeline("a ;") == ["a"]
    assert split_pipeline("a |") == ["a"]


# has_unquoted_heredoc — quote-aware heredoc detection .


def test_unquoted_real_heredoc_detected():
    assert has_unquoted_heredoc("cat <<EOF\nbody\nEOF") is True


def test_double_quoted_heredoc_literal_not_detected():
    assert has_unquoted_heredoc('grep -n "python3 - <<" file') is False


def test_single_quoted_heredoc_literal_not_detected():
    assert has_unquoted_heredoc("grep 'cat - <<EOF'") is False


def test_escaped_heredoc_not_detected():
    assert has_unquoted_heredoc(r"echo \<\< marker") is False


def test_here_string_still_detected():
    # ``<<<`` starts with ``<<`` — still flagged so the parser fails closed.
    assert has_unquoted_heredoc("foo <<< $bar") is True


def test_empty_segment_returns_false():
    assert has_unquoted_heredoc("") is False
    assert has_unquoted_heredoc("a single token") is False


def test_unquoted_newline_splits_statements():
    # Multi-line shell body without explicit `;` must split on newlines.
    # Without this, the first verb on line 1 absorbs every token from
    # the following lines as positional arguments.
    assert split_pipeline("a\nb\nc") == ["a", "b", "c"]
    assert split_pipeline(
        "tee /tmp/out.log\n_rc=${PIPESTATUS[0]}\ntail -80 /tmp/out.log"
    ) == ["tee /tmp/out.log", "_rc=${PIPESTATUS[0]}", "tail -80 /tmp/out.log"]


def test_quoted_newline_does_not_split():
    # A literal newline inside a double-quoted string stays in the
    # token (shell treats it as part of the string).
    assert split_pipeline('echo "a\nb"') == ['echo "a\nb"']


def test_heredoc_body_newlines_are_opaque():
    # When the command contains an unquoted heredoc, the body lines
    # must NOT split — splitting would parse prose lines as shell
    # statements (field-note 8667 was a docs-only apply_patch heredoc).
    cmd = "apply_patch <<'EOF'\n*** Begin Patch\nExternalWebapp and webapp\n*** End Patch\nEOF"
    assert split_pipeline(cmd) == [cmd]
