"""Stable SQL text for board record/replay lookup keys.

Board queries are authored as multiline Python strings, so indentation and
line wrapping are not part of their identity. SQL literal and comment bodies
are different: their bytes can affect the statement or its meaning to a
reader, and must remain part of the key unchanged.
"""

from __future__ import annotations

import re


_DOLLAR_QUOTE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def canonicalize_sql(sql: str) -> str:
    """Collapse whitespace outside SQL literals and comments.

    Single- and double-quoted spans preserve doubled-quote escapes. PostgreSQL
    dollar-quoted strings preserve the body selected by their exact tag.
    Line-comment terminators remain newlines because replacing one with a
    space would extend the comment over the following SQL token.
    """
    pieces: list[str] = []
    pending_space = False
    index = 0

    while index < len(sql):
        if sql[index].isspace():
            pending_space = True
            index += 1
            continue

        if pending_space:
            if pieces and pieces[-1] != "\n":
                pieces.append(" ")
            pending_space = False

        if sql.startswith("--", index):
            token, index, terminated = _consume_line_comment(sql, index)
            pieces.append(token)
            if terminated:
                pieces.append("\n")
            continue

        if sql.startswith("/*", index):
            token, index = _consume_block_comment(sql, index)
            pieces.append(token)
            continue

        char = sql[index]
        if char in {"'", '"'}:
            token, index = _consume_quoted(sql, index, char)
            pieces.append(token)
            continue

        if char == "$":
            dollar_quoted = _consume_dollar_quoted(sql, index)
            if dollar_quoted is not None:
                token, index = dollar_quoted
                pieces.append(token)
                continue

        pieces.append(char)
        index += 1

    if pieces and pieces[-1] == "\n":
        pieces.pop()
    return "".join(pieces)


def _consume_quoted(sql: str, start: int, quote: str) -> tuple[str, int]:
    """Return one quoted span, preserving doubled quote escapes."""
    index = start + 1
    while index < len(sql):
        if sql[index] != quote:
            index += 1
            continue
        if index + 1 < len(sql) and sql[index + 1] == quote:
            index += 2
            continue
        index += 1
        break
    return sql[start:index], index


def _consume_dollar_quoted(sql: str, start: int) -> tuple[str, int] | None:
    """Return one complete PostgreSQL dollar-quoted span when present."""
    match = _DOLLAR_QUOTE.match(sql, start)
    if match is None:
        return None
    delimiter = match.group(0)
    closing = sql.find(delimiter, match.end())
    if closing < 0:
        return None
    end = closing + len(delimiter)
    return sql[start:end], end


def _consume_line_comment(sql: str, start: int) -> tuple[str, int, bool]:
    """Preserve comment text and normalize its terminating line break."""
    index = start + 2
    while index < len(sql) and sql[index] not in {"\r", "\n"}:
        index += 1
    token = sql[start:index]
    if index == len(sql):
        return token, index, False
    if sql[index : index + 2] == "\r\n":
        index += 2
    else:
        index += 1
    return token, index, True


def _consume_block_comment(sql: str, start: int) -> tuple[str, int]:
    """Preserve one PostgreSQL block comment, including nested comments."""
    depth = 1
    index = start + 2
    while index < len(sql) and depth:
        if sql.startswith("/*", index):
            depth += 1
            index += 2
        elif sql.startswith("*/", index):
            depth -= 1
            index += 2
        else:
            index += 1
    return sql[start:index], index


__all__ = ["canonicalize_sql"]
