"""Shell-text preprocessing for :mod:`lint_raw_pytest_full_suite`.

A command that only WRITES a pytest command string as data — a QA
plan-case JSON payload authored via heredoc, or piped through
``printf``/``cat`` into a scratch file — reads, to a naive scan, as if
it ran that invocation: the guard's segment splitter does not respect
quoting or heredoc bodies, so text that is really a stored argument or
file body gets treated as a fresh, executable statement.

The two passes below POSITIVELY recognize the evidenced inert-write
shapes rather than guessing from a negative signal ("not a known
shell", "line starts with a sink"): each requires an unquoted ``>``
(the "this becomes a file" signal) on a single, self-contained
statement with no OTHER unquoted ``;``/``&``/``|`` riding along, AND —
for a heredoc — that the exact reading program is one of the two known
to only write or print its input (`cat`, `python3`), not merely absent
from a shell denylist. A compound or uncertain form — a heredoc read by a
launcher-wrapped or piped shell (``env bash <<EOF``, ``env bash >
out.log <<EOF``, ``cat <<EOF | bash``), or a sink-leading line that
also carries a second, different statement (``echo ok > /tmp/x; bash
-c '... && pytest ...'``) — fails that shape and is left completely
untouched, so it is scanned exactly as before by the guard's existing
(if incomplete) segment split. Recursing into a quoted, genuinely
executable payload (``bash -c "..."``, ``eval "..."``) to decide
whether IT invokes pytest is deliberately out of scope: that is a new
detection capability, not a fix to the false-positive shapes below.

* :func:`strip_heredoc_bodies` removes a heredoc body only when its
  launch line is that single, self-contained, redirected-to-a-file
  statement AND its reading program is exactly one of
  `_HEREDOC_DATA_READERS`. Every other reader — `sh`/`bash`/`zsh` (which
  interpret their heredoc body as shell commands line by line, so a
  standalone ``pytest ...`` line there is a real invocation),
  `env`-launched anything, and anything unrecognized — is left alone,
  redirect or not.
* :func:`mask_data_sink_lines` blanks quoted interiors only on that
  same shape of physical line, with a known data-writing program
  (`cat`/`printf`/`echo`/`tee`) in place of a heredoc's reading
  program — the shape a QA plan-case JSON payload actually takes.
"""

from __future__ import annotations

import re
from typing import List, Optional

_HEREDOC_START = re.compile(
    r"<<-?\s*(?:'(?P<sq>[^']*)'|\"(?P<dq>[^\"]*)\"|(?P<bare>[A-Za-z_]\w*))"
)

#: Readers whose own heredoc is proven inert: ``cat`` writing it to a
#: scratch file, ``python3`` printing one. Anything else, including a
#: launcher-wrapped or unrecognized reader, is a burden-of-proof
#: failure and is left untouched: a positive admit list, never a
#: "not a known shell" guess.
_HEREDOC_DATA_READERS = frozenset({"cat", "python3"})

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


#: Characters this module's guards look for outside quotes: ``>`` is the
#: positive "written to a file" signal; ``;``/``&``/``|`` each end one
#: statement, so any of them means another statement rides along.
_WATCHED_CHARS = frozenset({">", ";", "&", "|"})


def _unquoted_chars(text: str) -> frozenset[str]:
    """Return the subset of `_WATCHED_CHARS` appearing outside quotes."""
    found: set = set()
    i, n = 0, len(text)
    in_single = in_double = False
    while i < n:
        ch = text[i]
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
        if not in_single and not in_double and ch in _WATCHED_CHARS:
            found.add(ch)
        i += 1
    return frozenset(found)


def mask_data_sink_lines(command: str) -> str:
    """Blank quoted interiors on a standalone data-sink line.

    A line qualifies only when it is a single, self-contained statement:
    its leading word is a data-sink program, it has an unquoted ``>``,
    and it carries no OTHER unquoted ``;``/``&``/``|`` — the positive
    shape a QA plan-case JSON payload actually takes
    (``printf '...' > file``). Anything else is returned unchanged,
    including ``echo ok > /tmp/x; bash -c '... && pytest ...'``, whose
    second statement is a different, uncertain command riding the same
    physical line, and ``bash -c "... && pytest ..."`` on its own,
    whose quoted argument this guard's existing segment scan already
    reads as ordinary text.
    """
    out_lines = []
    for line in command.split("\n"):
        chars = _unquoted_chars(line)
        qualifies = (
            _leading_program(line) in _DATA_SINK_PROGRAMS
            and ">" in chars
            and not (chars & {";", "&", "|"})
        )
        out_lines.append(mask_quoted_spans(line) if qualifies else line)
    return "\n".join(out_lines)


def strip_heredoc_bodies(command: str) -> str:
    """Remove a heredoc body from *command* when it is written data.

    Scans for the next unquoted ``<<``/``<<-`` operator (a here-string
    ``<<<`` takes no body block and is left untouched). The body is
    stripped only when BOTH hold: its launch line is a single,
    self-contained statement redirected to a file — an unquoted ``>``
    present and no OTHER unquoted ``;``/``&``/``|`` — and its exact
    reading program is one proven inert by evidence (`_HEREDOC_DATA_
    READERS`). A launch line with no redirect (``bash <<'EOF'``, a
    genuine sweep), one riding a pipe into another program (``cat
    <<'EOF' | bash``), or one whose reader is unrecognized or
    launcher-wrapped even WITH a redirect (``env bash > out.log
    <<'EOF'`` still forwards to bash, which executes the body) fails
    this shape and is left completely untouched, so its body stays
    scannable exactly as before. Otherwise the full launch line is kept
    intact and every line up to and including the terminator — tab-
    stripped when the operator is ``<<-`` — is discarded; an
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
        line_start = command.rfind("\n", 0, i) + 1
        line_end = command.find("\n", i)
        if line_end == -1:
            line_end = n
        launch_line = command[line_start:line_end]
        chars = _unquoted_chars(launch_line)
        if (
            _leading_program(command[line_start:i]) not in _HEREDOC_DATA_READERS
            or ">" not in chars
            or (chars & {";", "&", "|"})
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


__all__ = ["mask_data_sink_lines", "mask_quoted_spans", "strip_heredoc_bodies"]
