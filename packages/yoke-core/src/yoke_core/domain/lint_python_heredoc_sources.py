"""Locate executable Python heredoc sources in parsed shell segments."""

from typing import List, Tuple

from yoke_contracts.hook_runner.shell_parse import ShellParse

_PYTHON = frozenset({"python", "python3"})


def python_sources(parsed: ShellParse) -> List[Tuple[int, str]]:
    """Return ``(segment index, body)`` for each heredoc a Python segment reads."""
    spans: List[Tuple[int, int, int]] = []
    cursor = 0
    for index, segment in enumerate(parsed.segments):
        start = parsed.code.find(segment.text, cursor)
        if start >= 0:
            cursor = start + len(segment.text)
            spans.append((start, cursor, index))
    sources: List[Tuple[int, str]] = []
    for heredoc in parsed.heredocs:
        index = next(
            (i for start, end, i in spans if start <= heredoc.operator_offset < end),
            None,
        )
        if index is None or parsed.segments[index].program not in _PYTHON:
            continue
        body = heredoc.body
        if parsed.code.startswith("<<-", heredoc.operator_offset):
            body = "\n".join(line.lstrip("\t") for line in body.split("\n"))
        sources += [(index, body)]
    return sources


