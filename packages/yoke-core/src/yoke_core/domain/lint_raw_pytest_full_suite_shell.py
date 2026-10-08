"""Separate known data-reader heredocs from executable shell source.

Direct cat/Python readers and registered item-content stdin writers consume
data, even without a file redirect. Shell, piped, launcher-wrapped and unknown
readers remain scannable. Unquoted data bodies retain executable substitutions;
quoted delimiters keep bodies literal. Ordinary argv needs no masking.
"""

from __future__ import annotations

import re
import shlex
from typing import List, Optional

from yoke_core.domain.path_claim_bash_substitution import executable_substitutions
from yoke_core.domain.path_claim_bash_splitter import split_pipeline

_HEREDOC_START = re.compile(
    r"<<-?\s*(?:'(?P<sq>[^']*)'|\"(?P<dq>[^\"]*)\"|(?P<bare>[A-Za-z_]\w*))"
)

# Direct known readers consume text or Python source rather than shell source.
# Unknown readers and pipes retain conservative inspection.
_HEREDOC_DATA_READERS = frozenset({"cat", "python3"})

_STDIN_DATA_WRITERS = (
    ("yoke", "items", "progress-log", "append"),
    ("yoke", "items", "structured-field", "replace"),
)


def _stdin_data_writer(line: str) -> bool:
    """Recognize registered item content writers, never arbitrary stdin use."""
    try:
        argv = shlex.split(line)
    except ValueError:
        return False
    if argv:
        argv[0] = argv[0].rsplit("/", 1)[-1]
    return "--stdin" in argv and any(
        tuple(argv[: len(prefix)]) == prefix for prefix in _STDIN_DATA_WRITERS
    )


def _leading_program(text: str) -> str:
    """First non-flag, non-assignment word in *text*, or ``""``."""
    for token in text.split():
        token = token.lstrip("({")
        if not token or token.startswith("-") or "=" in token:
            continue
        return token.rsplit("/", 1)[-1]
    return ""


def strip_heredoc_bodies(command: str) -> str:
    """Remove known data bodies while retaining their shell expansions.

    Recognition requires a direct known reader or a registered item-content
    writer, on a standalone launch line without another statement or pipe.
    Shell interpreters, launcher-wrapped readers, pipes and unknown readers
    stay scannable. Quoted delimiters suppress expansions; unquoted delimiters
    retain executable substitution bodies. Unterminated data stays data.
    """
    out: List[str] = []
    i, n = 0, len(command)
    in_single = in_double = False
    while i < n:
        ch = command[i]
        if ch == "\\" and not in_single and i + 1 < n:
            out.append(command[i : i + 2])
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
            in_single
            or in_double
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
        data_reader = (
            _leading_program(command[line_start:i]) in _HEREDOC_DATA_READERS
        ) or _stdin_data_writer(launch_line)
        if (
            not data_reader
            or len(split_pipeline(launch_line, split_background=True)) != 1
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
    if match.group("bare"):
        # An unquoted heredoc expands substitutions even though its plain
        # text is written data. Quotes in that body are literal characters.
        _, sources = executable_substitutions(
            command[launch_line_end + 1 : term_match.start()],
            literal_quotes=True,
        )
        out.extend("\n" + source for source in sources)
    out.append("\n")
    return term_match.end()


__all__ = ["strip_heredoc_bodies"]
