"""Extract concrete write destinations from Python fed through heredocs.

Only paths occupying a real write position count as destinations: the
receiver of a path write method, or the file operand of an ``open`` call
in a writing mode. A path the body merely *mentions* — a search string, a
replacement operand, text being stripped from documentation, a literal in
a comment — is string data, never a write target, and is not returned.

A write whose destination cannot be resolved (a loop operand, a variable
bound outside the body, a computed join) is reported separately as an
unresolved write rather than silently dropped, so a caller that must fail
closed can name the ambiguity instead of blaming a path the body never
wrote to.
"""

from __future__ import annotations

import ast
import shlex
from dataclasses import dataclass
from pathlib import PurePath
from typing import List, Optional, Tuple

from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    extract_heredoc_sections,
    strip_env_prefixes,
)


_PATH_WRITE_METHODS = frozenset({"write_text", "write_bytes", "touch", "mkdir"})
# Receivers that read wrong without parentheses: ``WT / rel.write_text``
# names a different expression than ``(WT / rel).write_text``.
_NEEDS_PARENS = (ast.BinOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.UnaryOp)


@dataclass(frozen=True)
class PythonWriteAnalysis:
    """Resolved write destinations plus the ones that stayed unreadable."""

    targets: Tuple[str, ...]
    detected: bool
    unresolved_writes: Tuple[str, ...] = ()


def analyze_python_heredoc_writes(command: str) -> PythonWriteAnalysis:
    """Parse executable Python heredoc bodies and return literal destinations."""
    targets: List[str] = []
    unresolved: List[str] = []
    detected = False
    for source in _python_sources(command):
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        visitor = _PythonWriteVisitor()
        visitor.visit(tree)
        targets.extend(visitor.targets)
        unresolved.extend(visitor.unresolved_writes)
        detected = detected or visitor.detected
    return PythonWriteAnalysis(
        _dedupe(targets), detected, _dedupe(unresolved),
    )


def _python_sources(command: str) -> List[str]:
    sources: List[str] = []
    for opener, body in extract_heredoc_sections(command):
        try:
            tokens = strip_env_prefixes(shlex.split(opener))
        except ValueError:
            continue
        if tokens and PurePath(tokens[0]).name in {"python", "python3"}:
            sources += [body]
    return sources


def _dedupe(paths: List[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(path for path in paths if path.strip()))


class _PythonWriteVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.bindings: dict[str, str] = {}
        self.targets: List[str] = []
        self.unresolved_writes: List[str] = []
        self.detected = False

    def visit_Assign(self, node: ast.Assign) -> None:
        path = self._path_value(node.value)
        if path is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.bindings[target.id] = path
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _PATH_WRITE_METHODS:
            self.detected = True
            self._record_write(self._path_value(func.value), node)
        elif self._is_write_open(node):
            self.detected = True
            if isinstance(func, ast.Attribute):
                bound_path = self._path_value(func.value)
                target = bound_path if bound_path is not None else self._first_arg(node)
            else:
                target = self._first_arg(node)
            self._record_write(target, node)
        self.generic_visit(node)

    def _is_write_open(self, node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            return self._mode_writes(node, 1)
        if isinstance(func, ast.Attribute) and func.attr == "open":
            mode_index = 0 if self._path_value(func.value) is not None else 1
            return self._mode_writes(node, mode_index)
        return False

    @staticmethod
    def _mode_writes(node: ast.Call, index: int) -> bool:
        mode: Optional[ast.AST] = node.args[index] if len(node.args) > index else None
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        return (
            isinstance(mode, ast.Constant)
            and isinstance(mode.value, str)
            and any(flag in mode.value for flag in "wax+")
        )

    def _first_arg(self, node: ast.Call) -> Optional[str]:
        return self._path_value(node.args[0]) if node.args else None

    def _path_value(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            is_path = (
                isinstance(func, ast.Name) and func.id == "Path"
                or isinstance(func, ast.Attribute) and func.attr == "Path"
            )
            if is_path:
                return self._path_value(node.args[0])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = self._path_value(node.left)
            right = self._path_value(node.right)
            if left is not None and right is not None:
                return str(PurePath(left).joinpath(right))
        return None

    def _record_write(self, path: Optional[str], node: ast.Call) -> None:
        """Keep a resolved destination, or name the one that stayed unread."""
        if path:
            self.targets += [path]
            return
        self.unresolved_writes += [_describe_write(node)]


def _describe_write(node: ast.Call) -> str:
    """Render the write expression whose destination could not be read."""
    func = node.func
    try:
        if isinstance(func, ast.Attribute):
            receiver = ast.unparse(func.value)
            if isinstance(func.value, _NEEDS_PARENS):
                receiver = f"({receiver})"
            return f"{_clip(receiver)}.{func.attr}(...)"
        head = ast.unparse(node.args[0]) if node.args else ""
        return f"{ast.unparse(func)}({_clip(head)}, ...)"
    except (AttributeError, ValueError):  # pragma: no cover - unparse floor
        return "<write with an unreadable destination>"


def _clip(text: str, limit: int = 60) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."


__all__ = ["PythonWriteAnalysis", "analyze_python_heredoc_writes"]
