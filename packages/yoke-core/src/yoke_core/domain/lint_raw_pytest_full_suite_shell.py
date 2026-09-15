"""Shell-text preprocessing for :mod:`lint_raw_pytest_full_suite`.

A command that only WRITES a pytest command string as data — a QA
plan-case JSON payload authored via heredoc, or piped through
``printf``/``cat`` into a scratch file — reads, to a naive scan, as if
it ran that invocation: the guard's segment splitter does not respect
quoting or heredoc bodies, so text that is really a stored argument or
file body gets treated as a fresh, executable statement.

The two passes below are scoped as narrowly as the evidence: they
recognize a small, explicit set of DATA-WRITING shapes and leave every
other command untouched, so a pytest invocation genuinely chained
after a real separator (``cmd && pytest ...``) — including one sitting
in a shell interpreter's own heredoc body, or a quoted ``-c`` argument
the caller intends to execute — keeps being scanned exactly as before.
Recursing into a quoted, genuinely executable payload (``bash -c
"..."``, ``eval "..."``) to decide whether IT invokes pytest is
deliberately out of scope: that is a new detection capability, not a
fix to the false-positive shapes below.

* :func:`strip_heredoc_bodies` removes a heredoc body only when its
  reading program is not a shell interpreter. `cat`, `python3`, and
  similar treat their heredoc as file content or script input that may
  merely MENTION pytest as text; `sh`/`bash`/`zsh` interpret their
  heredoc body as shell commands line by line, so a standalone
  ``pytest ...`` line there is a real invocation and stays scannable.
* :func:`mask_data_sink_lines` blanks quoted interiors only on a
  physical line whose leading word is a known data-writing sink
  (`cat`/`printf`/`echo`/`tee`) redirected to a file — the shape a QA
  plan-case JSON payload actually takes. Every other line, including a
  genuinely executable ``bash -c "..."`` argument, is left untouched.
"""

from __future__ import annotations

import re
from typing import List, Optional

_HEREDOC_START = re.compile(
    r"<<-?\s*(?:'(?P<sq>[^']*)'|\"(?P<dq>[^\"]*)\"|(?P<bare>[A-Za-z_]\w*))"
)

#: Interpreters that read a heredoc body as shell commands, line by
#: line — a bare ``pytest ...`` line there is a real invocation.
_SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "ksh", "dash"})

#: Programs whose ordinary job is writing their argument/stdin as data.
_DATA_SINK_PROGRAMS = frozenset({"cat", "printf", "echo", "tee"})


def _leading_program(text: str) -> str:
    """First non-flag, non-assignment word in *text*, or ``""``."""
    for token in text.split():
        token = token.lstrip("({")
        if not token or token.startswith("-") or "=" in token:
            continue
        return token.rsplit("/", 1)[-1]
    return ""


def mask_quoted_spans(text: str) -> str:
    """Blank the interior of every single/double-quoted span in *text*.

    Quote delimiters are kept so a flag that consumes "the next token"
    (``-k ''``) still has an (empty) token to consume. Backslash escapes
    a following character outside quotes and inside double quotes
    (``\\"`` does not close the span); single quotes have no escape in
    real shell syntax, so a backslash there is just another masked char.
    """
    out: List[str] = []
    i, n = 0, len(text)
    in_single = in_double = False
    while i < n:
        ch = text[i]
        if ch == "\\" and not in_single and i + 1 < n:
            if in_double:
                i += 2
                continue
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if in_single or in_double:
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_unquoted_gt(line: str) -> bool:
    """True iff ``>`` appears outside single/double quotes in *line*."""
    i, n = 0, len(line)
    in_single = in_double = False
    while i < n:
        ch = line[i]
        if ch == "\\" and not in_single and i + 1 < n:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if not in_single and not in_double and ch == ">":
            return True
        i += 1
    return False


def mask_data_sink_lines(command: str) -> str:
    """Blank quoted interiors on a data-sink line redirected to a file.

    A line whose leading word is not a data-sink program, or that has
    no unquoted ``>``/``>>``, is returned unchanged — including a
    ``bash -c "... && pytest ..."`` line, whose quoted argument this
    guard's existing segment scan already reads as ordinary text.
    """
    return "\n".join(
        mask_quoted_spans(line)
        if _leading_program(line) in _DATA_SINK_PROGRAMS and _has_unquoted_gt(line)
        else line
        for line in command.split("\n")
    )


def strip_heredoc_bodies(command: str) -> str:
    """Remove a heredoc body from *command* when it is written data.

    Scans for the next unquoted ``<<``/``<<-`` operator (a here-string
    ``<<<`` takes no body block and is left untouched). When the
    current line's leading program is a shell interpreter, the operator
    is left as ordinary text and its body stays scannable. Otherwise
    the full launch line is kept intact and every line up to and
    including the terminator — tab-stripped when the operator is
    ``<<-`` — is discarded; an unterminated heredoc discards the
    remainder as still-open data rather than guessing where it ends.
    """
    out: List[str] = []
    i, n = 0, len(command)
    in_single = in_double = False
    while i < n:
        ch = command[i]
        if ch == "\\" and not in_single and i + 1 < n:
            out.append(command[i:i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if (
            in_single or in_double
            or not command.startswith("<<", i)
            or command.startswith("<<<", i)
        ):
            out.append(ch)
            i += 1
            continue
        line_start = command.rfind("\n", 0, i) + 1
        if _leading_program(command[line_start:i]) in _SHELL_INTERPRETERS:
            out.append(ch)
            i += 1
            continue
        consumed = _consume_heredoc(command, i, out)
        if consumed is None:
            out.append(ch)
            i += 1
            continue
        i = consumed
    return "".join(out)


def _consume_heredoc(command: str, i: int, out: List[str]) -> Optional[int]:
    """Append the launch line and skip the body; return the new index."""
    match = _HEREDOC_START.match(command, i)
    if match is None:
        return None
    delimiter = match.group("sq") or match.group("dq") or match.group("bare")
    strip_tabs = command.startswith("<<-", i)
    launch_line_end = command.find("\n", match.end())
    if launch_line_end == -1:
        out.append(command[i:])
        return len(command)
    out.append(command[i:launch_line_end])
    indent = r"[ \t]*" if strip_tabs else ""
    terminator = re.compile(rf"(?m)^{indent}{re.escape(delimiter)}[ \t]*$")
    term_match = terminator.search(command, launch_line_end + 1)
    if term_match is None:
        return len(command)
    out.append("\n")
    return term_match.end()


__all__ = ["mask_data_sink_lines", "mask_quoted_spans", "strip_heredoc_bodies"]
