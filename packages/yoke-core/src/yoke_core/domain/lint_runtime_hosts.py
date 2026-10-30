"""Detect fixed hosted authorities in executable runtime strings."""

from __future__ import annotations

import ast
import re

# Documentation URLs are stable public navigation, not a selected service.
HOST_RE = re.compile(r"https?://(?:[a-z0-9-]+\.)*upyoke\.com\b(?:/[^\s\"'`<>]*)?")


def host_literals(relpath: str, text: str) -> list[tuple[int, str, str]]:
    if relpath.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        values = (
            (node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        )
    else:
        values = (
            (index, line)
            for index, line in enumerate(text.splitlines(), 1)
            if not line.lstrip().startswith(("//", "/*", "*"))
        )
    return [
        (line, f"fixed hosted authority {match.group(0)!r}", "runtime_host")
        for line, value in values
        for match in HOST_RE.finditer(value)
        if not re.search(r"/docs(?:/|$|[;.,)])", match.group(0))
    ]
