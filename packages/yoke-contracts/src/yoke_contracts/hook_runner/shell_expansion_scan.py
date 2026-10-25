"""Tell apart command text a shell expands from text it passes through literally.

Bash guards that object to command substitution need this distinction, and
quoting is what carries it. Single quotes are literal; double quotes expand.
A heredoc follows the same split through its delimiter: ``<<'EOF'`` is literal
all the way to the terminator, while a bare ``<<EOF`` expands its body exactly
like a double-quoted string. Scanning without that model reads literal prose as
if the shell were about to run it, which denies text that was never a hazard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEREDOC_RE = re.compile(
    r"<<(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z_][A-Za-z0-9_]*))"
    r"(?=$|[ \t\r\n;|&<>])"
)


@dataclass(frozen=True)
class Heredoc:
    """One heredoc body, and whether the shell expands it."""

    operator_offset: int
    delimiter: str
    expands: bool
    body: str
    source_operator_start: int
    source_operator_end: int
    source_body_start: int
    source_body_end: int


@dataclass(frozen=True)
class ScannedCommand:
    """A command with its heredoc bodies lifted out of the command text.

    ``code`` keeps every heredoc operator but none of the body lines, so a
    scan over it sees only text the shell parses as command syntax. Offsets
    into ``code`` are what ``Heredoc.operator_offset`` and
    ``shell_statements.pipeline_spans`` report.
    """

    code: str
    heredocs: tuple[Heredoc, ...]


def scan(command: str) -> ScannedCommand:
    """Split ``command`` into command text and the heredoc bodies it feeds."""
    chunks: list[str] = []
    code_length = 0
    heredocs: list[Heredoc] = []
    pending: list[tuple[int, str, bool, bool, int, int]] = []
    index = 0
    in_single = False
    in_double = False
    while index < len(command):
        char = command[index]
        if char == "\\" and not in_single:
            chunks.append(command[index : index + 2])
            code_length += len(command[index : index + 2])
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "#" and (index == 0 or command[index - 1].isspace()):
                end = command.find("\n", index)
                if end == -1:
                    end = len(command)
                chunks.append(command[index:end])
                code_length += end - index
                index = end
                continue
            if command.startswith("<<<", index):
                chunks.append("<<<")
                code_length += 3
                index += 3
                continue
            match = (
                _HEREDOC_RE.match(command, index)
                if command.startswith("<<", index)
                else None
            )
            if match is not None:
                quoted = match.group(2) is not None or match.group(3) is not None
                delimiter = match.group(2) or match.group(3) or match.group(4) or ""
                pending.append(
                    (
                        code_length,
                        delimiter,
                        not quoted,
                        match.group(1) == "-",
                        index,
                        match.end(),
                    )
                )
                chunks.append(match.group(0))
                code_length += len(match.group(0))
                index = match.end()
                continue
            if char == "\n" and pending:
                chunks.append("\n")
                code_length += 1
                index += 1
                for offset, delimiter, expands, strip_tabs, start, end in pending:
                    body_start = index
                    body, index = _consume_body(command, index, delimiter, strip_tabs)
                    heredocs.append(
                        Heredoc(
                            offset,
                            delimiter,
                            expands,
                            body,
                            start,
                            end,
                            body_start,
                            index,
                        )
                    )
                pending = []
                continue
        chunks.append(char)
        code_length += 1
        index += 1
    return ScannedCommand("".join(chunks), tuple(heredocs))


def strip_literal_heredocs(command: str) -> str:
    """Remove quoted heredoc inputs, retaining redirects and real commands.

    Quoted bodies are literal input, including apostrophes, operators and
    substitution spellings. Expanding heredocs retain their original source
    for the caller's conservative analysis.
    """
    if "<<" not in command:
        return command
    spans = []
    for heredoc in scan(command).heredocs:
        if not heredoc.expands:
            spans.extend(
                (
                    (heredoc.source_operator_start, heredoc.source_operator_end),
                    (heredoc.source_body_start, heredoc.source_body_end),
                )
            )
    chunks = []
    previous = 0
    for start, end in sorted(spans):
        chunks.extend((command[previous:start], " "))
        previous = end
    chunks.append(command[previous:])
    return "".join(chunks)


def _consume_body(
    command: str, index: int, delimiter: str, strip_tabs: bool
) -> tuple[str, int]:
    """Read heredoc body lines up to the terminator, or to the end of input."""
    body: list[str] = []
    while index < len(command):
        break_at = command.find("\n", index)
        if break_at == -1:
            line, next_index = command[index:], len(command)
        else:
            line, next_index = command[index:break_at], break_at + 1
        candidate = line.lstrip("\t") if strip_tabs else line
        if candidate.rstrip("\r") == delimiter:
            return "".join(body), next_index
        body.append(line + "\n")
        index = next_index
    return "".join(body), index


def double_quoted_spans(text: str) -> list[str]:
    """Return the double-quoted runs of ``text``, skipping single-quoted runs."""
    spans: list[str] = []
    current: list[str] = []
    index = 0
    in_single = False
    in_double = False
    while index < len(text):
        char = text[index]
        if char == "\\" and not in_single:
            if in_double:
                current.append(text[index : index + 2])
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            if in_double:
                spans.append("".join(current))
                current = []
            in_double = not in_double
        elif in_double:
            current.append(char)
        index += 1
    return spans


def has_substitution(text: str) -> bool:
    """Report whether ``text`` carries an unescaped backtick or ``$(``."""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "`" or text.startswith("$(", index):
            return True
        index += 1
    return False
