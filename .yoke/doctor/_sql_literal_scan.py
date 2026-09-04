"""Shared extraction of executable SQL text from Python and ``.sql`` sources.

Checks that ban a SQL shape have to distinguish source that RUNS the shape
from source that merely names it. A docstring explaining why a query is
banned, and a comment above the replacement, must never read as violations —
otherwise the fix for a check is to reword the prose that teaches it.

Underscore-prefixed on purpose: discovery imports ``check_*.py`` only, so
this module is a helper the checks share rather than a check itself.
"""

from __future__ import annotations

import ast
import re
from typing import Iterator, List, Tuple


_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_SQL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def sql_executable_text(source: str) -> str:
    """Return *source* with SQL comments blanked out."""
    stripped = _SQL_BLOCK_COMMENT_RE.sub(" ", source)
    return _SQL_LINE_COMMENT_RE.sub(" ", stripped)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()

    def _first_string(body: List[ast.stmt]) -> None:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            nodes.add(id(body[0].value))

    if isinstance(tree, ast.Module):
        _first_string(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _first_string(node.body)
    return nodes


def python_literal_strings(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """Yield ``(line, text)`` for every non-docstring string literal."""
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            parts = [
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ]
            if parts:
                yield node.lineno, "".join(parts)


__all__ = ["python_literal_strings", "sql_executable_text"]
