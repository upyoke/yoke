"""SQL shape guard for the ``db.read.run`` diagnostic read surface."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


_READ_START_WORDS = frozenset({"SELECT", "EXPLAIN", "WITH"})
_WRITE_WORDS = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE", "COPY", "CALL", "DO"})
_DDL_WORDS = frozenset({
    "ALTER",
    "ATTACH",
    "CLUSTER",
    "COMMENT",
    "CREATE",
    "DETACH",
    "DROP",
    "GRANT",
    "IMPORT",
    "INTO",
    "LABEL",
    "LISTEN",
    "LOCK",
    "NOTIFY",
    "PRAGMA",
    "REFRESH",
    "REINDEX",
    "RESET",
    "REVOKE",
    "SECURITY",
    "SET",
    "TRUNCATE",
    "VACUUM",
})
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOLLAR_TAG_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


@dataclass(frozen=True)
class DbReadRefusal:
    code: str
    message: str
    jsonpath: str = "$.payload.sql"


def validate_read_only_sql(sql: str) -> Optional[DbReadRefusal]:
    """Return a typed refusal when *sql* is not a single read-only statement."""
    statements = _split_sql_statements(sql)
    if not statements:
        return DbReadRefusal(code="sql_empty", message="sql must not be empty")
    if len(statements) > 1:
        return DbReadRefusal(
            code="sql_multiple_statements",
            message="db.read.run accepts exactly one SQL statement",
        )

    words = _sql_words(statements[0])
    if not words:
        return DbReadRefusal(code="sql_empty", message="sql must not be empty")
    write_word = next((word for word in words if word in _WRITE_WORDS), None)
    if write_word is not None:
        return DbReadRefusal(
            code="sql_write_refused",
            message=f"write statement token {write_word} is not allowed",
        )
    ddl_word = next((word for word in words if word in _DDL_WORDS), None)
    if ddl_word is not None:
        return DbReadRefusal(
            code="sql_ddl_refused",
            message=f"DDL/control statement token {ddl_word} is not allowed",
        )
    if words[0] not in _READ_START_WORDS:
        return DbReadRefusal(
            code="sql_not_read_only",
            message="db.read.run only accepts SELECT, EXPLAIN, or read-only WITH",
        )
    return None


def _split_sql_statements(sql: str) -> List[str]:
    statements: List[str] = []
    buf: List[str] = []
    state = "normal"
    dollar_tag = ""
    block_depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if state == "normal":
            if ch == "-" and nxt == "-":
                state = "line_comment"
                buf.extend([ch, nxt])
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                block_depth = 1
                buf.extend([ch, nxt])
                i += 2
                continue
            if ch == "'":
                state = "single_quote"
                buf.append(ch)
                i += 1
                continue
            if ch == '"':
                state = "double_quote"
                buf.append(ch)
                i += 1
                continue
            if ch == "$":
                match = _DOLLAR_TAG_RE.match(sql, i)
                if match is not None:
                    dollar_tag = match.group(0)
                    state = "dollar_quote"
                    buf.append(dollar_tag)
                    i = match.end()
                    continue
            if ch == ";":
                statement = "".join(buf).strip()
                if _sql_words(statement):
                    statements.append(statement)
                buf.clear()
                i += 1
                continue
        elif state == "line_comment":
            if ch == "\n":
                state = "normal"
        elif state == "block_comment":
            if ch == "/" and nxt == "*":
                block_depth += 1
                buf.extend([ch, nxt])
                i += 2
                continue
            if ch == "*" and nxt == "/":
                block_depth -= 1
                buf.extend([ch, nxt])
                i += 2
                if block_depth == 0:
                    state = "normal"
                continue
        elif state == "single_quote":
            if ch == "\\" and nxt:
                buf.extend([ch, nxt])
                i += 2
                continue
            if ch == "'" and nxt == "'":
                buf.extend([ch, nxt])
                i += 2
                continue
            if ch == "'":
                state = "normal"
        elif state == "double_quote":
            if ch == '"' and nxt == '"':
                buf.extend([ch, nxt])
                i += 2
                continue
            if ch == '"':
                state = "normal"
        elif state == "dollar_quote":
            if dollar_tag and sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                state = "normal"
                continue
        buf.append(ch)
        i += 1
    statement = "".join(buf).strip()
    if _sql_words(statement):
        statements.append(statement)
    return statements


def _sql_words(sql: str) -> List[str]:
    words: List[str] = []
    state = "normal"
    dollar_tag = ""
    block_depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if state == "normal":
            if ch == "-" and nxt == "-":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                block_depth = 1
                i += 2
                continue
            if ch == "'":
                state = "single_quote"
                i += 1
                continue
            if ch == '"':
                state = "double_quote"
                i += 1
                continue
            if ch == "$":
                match = _DOLLAR_TAG_RE.match(sql, i)
                if match is not None:
                    dollar_tag = match.group(0)
                    state = "dollar_quote"
                    i = match.end()
                    continue
            match = _WORD_RE.match(sql, i)
            if match is not None:
                words.append(match.group(0).upper())
                i = match.end()
                continue
        elif state == "line_comment":
            if ch == "\n":
                state = "normal"
        elif state == "block_comment":
            if ch == "/" and nxt == "*":
                block_depth += 1
                i += 2
                continue
            if ch == "*" and nxt == "/":
                block_depth -= 1
                i += 2
                if block_depth == 0:
                    state = "normal"
                continue
        elif state == "single_quote":
            if ch == "\\" and nxt:
                i += 2
                continue
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                state = "normal"
        elif state == "double_quote":
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                state = "normal"
        elif state == "dollar_quote":
            if dollar_tag and sql.startswith(dollar_tag, i):
                i += len(dollar_tag)
                state = "normal"
                continue
        i += 1
    return words


__all__ = ["DbReadRefusal", "validate_read_only_sql"]
