"""Reverse import graph over the repository's Python sources.

Sibling of :mod:`yoke_core.tools.impacted_tests`, which re-exports every
name here so callers keep one import site. Split out to keep the selector
under the authored-file line cap.

The index answers one question: given a module, which files reference it?
References are ordinary imports plus dotted-path **string literals** — a
test that spawns ``python3 -m pkg.tool``, patches ``"pkg.helper"`` by
string target, or dispatches through a string-keyed registry names its
dependency in a string, and only a string.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_PACKAGE_SOURCE_MARKER = "/src/"
_SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".worktrees", "build"}
)

#: A string literal shaped like a dotted module path is treated as a
#: dependency reference (subprocess ``-m`` targets, patch targets,
#: registry keys). Single-segment names are far too noisy to count.
_DOTTED_PATH = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


def is_test_file(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return name.startswith("test_") and name.endswith(".py")


def module_name_for(rel_path: str) -> "str | None":
    """Dotted module name for a repo-relative source path, if it is one."""
    if not rel_path.endswith(".py"):
        return None
    trimmed = rel_path[: -len(".py")]
    marker_at = trimmed.find(_PACKAGE_SOURCE_MARKER)
    if marker_at != -1:
        trimmed = trimmed[marker_at + len(_PACKAGE_SOURCE_MARKER) :]
    if trimmed.endswith("/__init__"):
        trimmed = trimmed[: -len("/__init__")]
    return trimmed.replace("/", ".")


def _iter_source_files(repo_root: Path) -> Iterable[Path]:
    # Skip on the path *relative to the root*, never the absolute one. A
    # linked worktree lives at ``<repo>/.worktrees/<branch>/``, so matching
    # absolute parts makes every file under it look like a skipped
    # directory and yields an empty index — which reads downstream as
    # "nothing is importable" and silently widens every run to a full
    # sweep, exactly where the selection is worth the most.
    for path in repo_root.rglob("*.py"):
        rel = path.relative_to(repo_root)
        if any(part in _SKIP_DIRECTORIES for part in rel.parts):
            continue
        if ".egg-info" in str(rel):
            continue
        yield path


def _imported_modules(tree: ast.AST, own_module: "str | None") -> set[str]:
    """Modules referenced by *tree*, including resolved relative imports."""
    package = own_module.rsplit(".", 1)[0] if own_module and "." in own_module else ""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                ancestor = package
                for _ in range(node.level - 1):
                    ancestor = ancestor.rsplit(".", 1)[0] if "." in ancestor else ""
                base = f"{ancestor}.{base}" if base else ancestor
            if not base:
                continue
            found.add(base)
            # ``from pkg import name`` may be importing a module or a symbol;
            # record both readings and let the index decide which exists.
            for alias in node.names:
                found.add(f"{base}.{alias.name}")
    return found


def _string_module_references(tree: ast.AST) -> set[str]:
    """Dotted-path string literals, expanded to every module prefix.

    ``"pkg.tool.main"`` may name a module or an attribute inside one, so
    every two-plus-segment prefix is recorded; prefixes that match no real
    module are inert keys in the reverse index. Strings that are not
    module paths (event names, function ids) cost nothing for the same
    reason — they only select something when a module actually matches.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.strip()
        if len(value) > 200 or not _DOTTED_PATH.match(value):
            continue
        parts = value.split(".")
        for end in range(2, len(parts) + 1):
            found.add(".".join(parts[:end]))
    return found


@dataclass(frozen=True)
class ImportIndex:
    """Reverse import edges plus the module name of every source file."""

    importers: dict[str, set[str]]
    module_of: dict[str, str]


def build_import_index(repo_root: Path) -> ImportIndex:
    importers: dict[str, set[str]] = {}
    module_of: dict[str, str] = {}
    for path in _iter_source_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        module = module_name_for(rel)
        if module:
            module_of[rel] = module
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        references = _imported_modules(tree, module) | _string_module_references(tree)
        for referenced in references:
            importers.setdefault(referenced, set()).add(rel)
    return ImportIndex(importers=importers, module_of=module_of)


__all__ = [
    "ImportIndex",
    "build_import_index",
    "is_test_file",
    "module_name_for",
]
