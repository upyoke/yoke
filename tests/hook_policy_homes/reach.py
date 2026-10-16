"""Static reach of server-run hook policies and the local reads inside it.

A hook chain policy whose home is not ``CLIENT``
(:mod:`yoke_contracts.hook_runner.policy_home`) may run on the control-plane
authority, which cannot see the client machine. This module walks every
function such a policy's ``evaluate`` can reach and reports each read of
machine-local state in it, so the guard test can require that every one is
either removed, fed by a client fact, or carries a written reason.

Reachability is a deliberate over-approximation over the AST: a reached
function reaches every function, class or module attribute it names
(including lazy imports in its body), and a reached class reaches all of its
methods. Calls through runtime values (``obj.method()``) are not followed.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator

REPO = Path(__file__).resolve().parents[2]
_PACKAGE_ROOTS = {
    "yoke_core": REPO / "packages/yoke-core/src",
    "yoke_contracts": REPO / "packages/yoke-contracts/src",
    "yoke_harness": REPO / "packages/yoke-harness/src",
    "yoke_cli": REPO / "packages/yoke-cli/src",
}

#: Policy source a reached runner executes with ``exec`` rather than
#: imports: runner module -> (owning module, attribute holding the source).
EXEC_SOURCES = {
    "yoke_core.domain.lint_db_runner": (
        "yoke_core.domain.lint_db_rules",
        "HOOK_POLICY_SOURCE",
    ),
}

_SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "check_call", "call"})
_OS_CALLS = frozenset(
    {
        "getcwd",
        "getenv",
        "listdir",
        "scandir",
        "walk",
        "stat",
        "lstat",
        "access",
        "readlink",
        "getlogin",
    }
)
_OS_PATH_CALLS = frozenset(
    {
        "exists",
        "isfile",
        "isdir",
        "islink",
        "realpath",
        "expanduser",
        "getmtime",
        "getsize",
        "lexists",
        "samefile",
    }
)
_PATH_METHODS = frozenset(
    {
        "exists",
        "is_file",
        "is_dir",
        "is_symlink",
        "stat",
        "lstat",
        "iterdir",
        "glob",
        "rglob",
        "resolve",
        "read_text",
        "read_bytes",
        "expanduser",
        "samefile",
        "readlink",
    }
)
_PATH_CLASSMETHODS = frozenset({"cwd", "home"})


@dataclass(frozen=True)
class LocalRead:
    """One read of machine-local state inside a reached function."""

    key: str  # "module:qualname"
    line: int
    kind: str


def module_path(name: str) -> Path | None:
    root = _PACKAGE_ROOTS.get(name.split(".")[0])
    if root is None:
        return None
    base = root / name.replace(".", "/")
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


class _Module:
    def __init__(self, name: str, path: Path) -> None:
        self.name = name
        self.tree = ast.parse(path.read_text(encoding="utf-8"))
        self.defs: dict[str, ast.AST] = {}
        self.aliases: dict[str, tuple[str, str | None]] = {}
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[node.name] = node
        package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.aliases[alias.asname] = (alias.name, None)
                    else:
                        top = alias.name.split(".")[0]
                        self.aliases[top] = (top, None)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".")
                    parts = parts[: len(parts) - (node.level - 1)]
                    base = ".".join([*parts, base] if base else parts)
                for alias in node.names:
                    local = alias.asname or alias.name
                    if module_path(f"{base}.{alias.name}"):
                        self.aliases[local] = (f"{base}.{alias.name}", None)
                    else:
                        self.aliases[local] = (base, alias.name)


@lru_cache(maxsize=None)
def _module(name: str) -> _Module | None:
    path = module_path(name)
    return _Module(name, path) if path else None


def _targets(mod: _Module, node: ast.AST) -> Iterator[tuple[str, str]]:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        if node.id in mod.defs:
            yield mod.name, node.id
        elif node.id in mod.aliases:
            target, attr = mod.aliases[node.id]
            if attr:
                yield target, attr
    elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        alias = mod.aliases.get(node.value.id)
        if alias is None:
            return
        target, attr = alias
        owner = target if attr is None else f"{target}.{attr}"
        if module_path(owner):
            yield owner, node.attr


def reach(seeds: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    """Return every ``(module, top-level name)`` the seeds can reach."""
    seen: set[tuple[str, str]] = set()
    stack = list(seeds)
    while stack:
        name, symbol = stack.pop()
        if (name, symbol) in seen:
            continue
        mod = _module(name)
        if mod is None:
            continue
        if symbol not in mod.defs:
            alias = mod.aliases.get(symbol)
            if alias is not None and alias[1] is not None:
                stack.append(alias)  # re-exported name
            continue
        seen.add((name, symbol))
        for node in ast.walk(mod.defs[symbol]):
            stack.extend(t for t in _targets(mod, node) if t not in seen)
    return seen


def _read_kind(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id == "__file__":
        return "__file__"
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "os" and node.attr == "environ":
            return "os.environ"
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return "open"
    if not isinstance(func, ast.Attribute):
        return None
    owner = func.value
    if isinstance(owner, ast.Name):
        if owner.id == "subprocess" and func.attr in _SUBPROCESS_CALLS:
            return f"subprocess.{func.attr}"
        if owner.id == "os" and func.attr in _OS_CALLS:
            return f"os.{func.attr}"
        if owner.id == "Path" and func.attr in _PATH_CLASSMETHODS:
            return f"Path.{func.attr}"
        if owner.id in {"glob", "shutil"} and func.attr in {"glob", "iglob", "which"}:
            return f"{owner.id}.{func.attr}"
    if (
        isinstance(owner, ast.Attribute)
        and isinstance(owner.value, ast.Name)
        and owner.value.id == "os"
        and owner.attr == "path"
        and func.attr in _OS_PATH_CALLS
    ):
        return f"os.path.{func.attr}"
    if func.attr in _PATH_METHODS:
        return f".{func.attr}()"
    return None


def _scan(
    tree: ast.AST, module: str, qualname: str, *, is_class: bool
) -> Iterator[LocalRead]:
    """Yield reads under *tree*; a class's reads report per method."""

    def visit(node: ast.AST, name: str) -> Iterator[LocalRead]:
        for child in ast.iter_child_nodes(node):
            if (
                is_class
                and node is tree
                and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                yield from visit(child, f"{qualname}.{child.name}")
                continue
            kind = _read_kind(child)
            if kind is not None:
                yield LocalRead(f"{module}:{name}", child.lineno, kind)
            yield from visit(child, name)

    yield from visit(tree, qualname)


def local_reads(reached: Iterable[tuple[str, str]]) -> list[LocalRead]:
    """Return every local read inside the reached top-level symbols."""
    reached = set(reached)
    out: list[LocalRead] = []
    for name, symbol in sorted(reached):
        mod = _module(name)
        node = mod.defs.get(symbol) if mod else None
        if node is not None:
            out.extend(
                _scan(node, name, symbol, is_class=isinstance(node, ast.ClassDef))
            )
    reached_modules = {name for name, _ in reached}
    for runner, (owner, attr) in EXEC_SOURCES.items():
        if runner in reached_modules:
            source = getattr(importlib.import_module(owner), attr)
            out.extend(_scan(ast.parse(source), owner, attr, is_class=False))
    return out


__all__ = ["EXEC_SOURCES", "LocalRead", "local_reads", "module_path", "reach"]
