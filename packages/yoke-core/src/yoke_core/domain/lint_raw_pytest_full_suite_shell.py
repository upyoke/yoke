"""Shell-text preprocessing for :mod:`lint_raw_pytest_full_suite`.

FN50157: the guard scanned raw command TEXT for a pytest invocation, so
a command that only WRITES a pytest command string as data — a QA
plan-case JSON payload authored via heredoc, or piped through
``printf``/``cat`` into a scratch file — was misread as running that
invocation. Neither shape executes anything; both embed the text as an
inert argument or file body.

Two narrow preprocessing passes make written data invisible to the
classifier before it ever segments or tokenizes the command, so the
existing segment-split-then-tokenize pipeline in the caller needs no
architecture change:

* :func:`strip_heredoc_bodies` removes each heredoc body outright — it
  is written file content, never executed shell text — regardless of
  whether the body happens to be quoted.
* :func:`mask_quoted_spans` blanks the interior of every remaining
  quoted span (keeping the delimiters so a flag consuming "the next
  token" still has one to consume), so a shell operator or a pytest
  invocation embedded in a quoted argument — ``printf '...json...'``,
  ``-k 'not slow'`` — never reads as executable text.

Recursing into a genuinely executable quoted payload (``bash -c
"..."``, ``eval "..."``) is deliberately out of scope: that is a new
detection capability, not a fix to this false-positive, and the
existing segment-split-on-a-real-separator path (``cmd && pytest ...``)
already catches a real chained invocation without either pass below.
"""

from __future__ import annotations

import re
from typing import List, Optional

_HEREDOC_START = re.compile(
    r"<<-?\s*(?:'(?P<sq>[^']*)'|\"(?P<dq>[^\"]*)\"|(?P<bare>[A-Za-z_]\w*))"
)


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


def strip_heredoc_bodies(command: str) -> str:
    """Remove each heredoc body from *command*; it is written data.

    Scans for the next unquoted ``<<``/``<<-`` operator (a here-string
    ``<<<`` takes no body block and is left untouched), keeps the full
    launch line intact, then discards every line up to and including the
    terminator line — tab-stripped when the operator is ``<<-``. An
    unterminated heredoc discards the remainder as still-open data
    rather than guessing where it ends.
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


__all__ = ["mask_quoted_spans", "strip_heredoc_bodies"]
