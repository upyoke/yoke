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
import posixpath
from dataclasses import dataclass
from pathlib import PurePath
from typing import List, Optional, Sequence, Tuple

from yoke_contracts.free_paths import STATIC_FREE_PATH_PREFIXES
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell

from yoke_core.domain.lint_session_cwd_target_extract_shell import in_segment_cwd


_PYTHON = frozenset({"python", "python3"})
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
    free_writes: bool = False


def analyze_python_heredoc_writes(
    command: str | ShellParse,
    *,
    protected_roots: Tuple[str, ...] = (),
    segment_cwds: Sequence[str] = (),
) -> PythonWriteAnalysis:
    """Parse executable Python heredoc bodies and return literal destinations."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    targets: List[str] = []
    unresolved: List[str] = []
    detected = False
    free_writes = False
    for index, source in _python_sources(parsed):
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        visitor = _PythonWriteVisitor(protected_roots)
        visitor.visit(tree)
        targets.extend(in_segment_cwd(visitor.targets, segment_cwds, index))
        unresolved.extend(visitor.unresolved_writes)
        detected = detected or visitor.detected
        free_writes = free_writes or visitor.free_writes
    return PythonWriteAnalysis(
        _dedupe(targets),
        detected,
        _dedupe(unresolved),
        free_writes,
    )


def _python_sources(parsed: ShellParse) -> List[Tuple[int, str]]:
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


def _dedupe(paths: List[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(path for path in paths if path.strip()))


class _PythonWriteVisitor(ast.NodeVisitor):
    def __init__(self, protected_roots: Tuple[str, ...]) -> None:
        self.protected_roots = tuple(posixpath.normpath(p) for p in protected_roots)
        self.bindings: dict[str, str] = {}
        self.targets: List[str] = []
        self.unresolved_writes: List[str] = []
        self.detected = False
        self.free_writes = False
        self.free_bindings: set[str] = set()
        self.tempfile_modules: set[str] = set()
        self.tempfile_factories: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "tempfile":
                self.tempfile_modules.add(alias.asname or alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "tempfile":
            for alias in node.names:
                if alias.name in {
                    "TemporaryDirectory",
                    "mkdtemp",
                    "NamedTemporaryFile",
                }:
                    self.tempfile_factories[alias.asname or alias.name] = alias.name

    def _tempfile_directory(self, node: ast.Call) -> ast.AST | None:
        func = node.func
        name = (
            self.tempfile_factories.get(func.id)
            if isinstance(func, ast.Name)
            else func.attr
        )
        index = 6 if name == "NamedTemporaryFile" else 2
        positional = node.args[index] if len(node.args) > index else None
        directory = next(
            (kw.value for kw in node.keywords if kw.arg == "dir"), positional
        )
        return (
            None
            if isinstance(directory, ast.Constant) and directory.value is None
            else directory
        )

    def _is_tempfile_factory(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (
            isinstance(func, ast.Name)
            and func.id in self.tempfile_factories
            or isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in self.tempfile_modules
            and func.attr in {"TemporaryDirectory", "mkdtemp", "NamedTemporaryFile"}
        )

    def _is_free_path(self, node: ast.AST) -> bool:
        path = self._path_value(node)
        if path is not None:
            normalized = posixpath.normpath(path)
            # A managed checkout may itself live under an OS temp root.
            if any(
                normalized == p or normalized.startswith(p + "/")
                for p in self.protected_roots
            ):
                return False
            return any(
                normalized == p or normalized.startswith(p + "/")
                for p in STATIC_FREE_PATH_PREFIXES
            )
        if isinstance(node, ast.Name):
            return node.id in self.free_bindings
        if self._is_tempfile_factory(node):
            directory = self._tempfile_directory(node)
            # Default tempfile storage is scratch; explicit destinations must
            # independently name a free root, never an arbitrary checkout.
            return directory is None or self._is_free_path(directory)
        if isinstance(node, ast.Attribute) and node.attr == "name":
            return self._is_free_path(node.value)
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            if (
                isinstance(func, ast.Name)
                and func.id == "Path"
                or isinstance(func, ast.Attribute)
                and func.attr == "Path"
            ):
                return self._is_free_path(node.args[0])
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
            right = self._path_value(node.right)
            if right is not None and ".." in PurePath(right).parts:
                return False
            if (
                isinstance(node.op, ast.Div)
                and right is not None
                and PurePath(right).is_absolute()
            ):
                return False
            return self._is_free_path(node.left)
        return False

    def _bind(self, target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Name):
            path = self._path_value(value)
            free = self._is_free_path(value)
            self.bindings.pop(target.id, None)
            self.free_bindings.discard(target.id)
            if path is not None:
                self.bindings[target.id] = path
            elif free:
                self.free_bindings.add(target.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._bind(target, node.value)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind(item.optional_vars, item.context_expr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _PATH_WRITE_METHODS:
            self.detected = True
            self._record_write(self._path_value(func.value), node, func.value)
        elif self._is_write_open(node):
            self.detected = True
            operand = (
                func.value
                if isinstance(func, ast.Attribute)
                and (
                    self._path_value(func.value) is not None
                    or self._is_free_path(func.value)
                )
                else (node.args[0] if node.args else node)
            )
            self._record_write(self._path_value(operand), node, operand)
        elif self._is_tempfile_factory(node):
            self.detected = True
            directory = self._tempfile_directory(node)
            if directory is None:
                self.free_writes = True
            else:
                self._record_write(self._path_value(directory), node, directory)
        self.generic_visit(node)

    def _is_write_open(self, node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            return self._mode_writes(node, 1)
        if isinstance(func, ast.Attribute) and func.attr == "open":
            mode_index = (
                0
                if self._path_value(func.value) is not None
                or self._is_free_path(func.value)
                else 1
            )
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

    def _path_value(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            is_path = (
                isinstance(func, ast.Name)
                and func.id == "Path"
                or isinstance(func, ast.Attribute)
                and func.attr == "Path"
            )
            if is_path:
                return self._path_value(node.args[0])
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = self._path_value(node.left)
            right = self._path_value(node.right)
            if left is not None and right is not None:
                return str(PurePath(left).joinpath(right))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = self._path_value(node.left), self._path_value(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    def _record_write(
        self, path: Optional[str], node: ast.Call, operand: ast.AST
    ) -> None:
        """Keep a resolved destination, or name the one that stayed unread."""
        if path:
            self.targets += [path]
            return
        if self._is_free_path(operand):
            self.free_writes = True
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
