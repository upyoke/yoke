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
from typing import Iterable, Sequence

from yoke_core.engines.doctor_project_checks import (
    PROJECT_CHECKS_DIR,
    PROJECT_CHECKS_PACKAGE,
)
from yoke_core.tools.impacted_project_test_roots import (
    YOKE_SEEDED_TEST_ROOTS,
    current_test_roots,
)
from yoke_core.tools._impacted_selection import is_effectively_full

_PACKAGE_SOURCE_MARKER = "/src/"
#: Project-local checks live here and import under
#: :data:`PROJECT_CHECKS_PACKAGE`; both facts belong to the engine that
#: loads them, so they are read from it rather than restated.
_PROJECT_CHECKS_PREFIX = f"{PROJECT_CHECKS_DIR.as_posix()}/"
_SKIP_DIRECTORIES = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".worktrees", "build"}
)

#: This checkout's own seeded test roots, for callers that describe a Yoke
#: sweep rather than resolve one. A live checkout answers through
#: :func:`current_test_roots`, whose declaration may differ per project.
TEST_ANCHORS = YOKE_SEEDED_TEST_ROOTS

#: A string literal shaped like a dotted module path is treated as a
#: dependency reference (subprocess ``-m`` targets, patch targets,
#: registry keys). Single-segment names are far too noisy to count.
_DOTTED_PATH = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")

#: A string literal shaped like a path to a Python file is also a
#: dependency reference. Contract rosters name their subjects that way —
#: the field-note consumer list and the workspace-anchored writer list
#: both do — so without this edge, editing a file a roster names leaves
#: the test guarding that roster unreachable, and CI is the first thing to
#: notice. A bare file name counts too, because a caller that assembles
#: its subject a segment at a time (``root / "pkg" / "thing.py"``) never
#: writes the whole path down; the caller resolves those only when the
#: name is unambiguous, so a ``conftest.py`` literal links to nothing.
_REPO_RELATIVE_PY = re.compile(r"^[\w.\-/]+\.py$")


def is_test_file(rel_path: str) -> bool:
    anchors = current_test_roots()
    name = rel_path.rsplit("/", 1)[-1]
    return (
        bool(anchors)
        and any(rel_path.startswith(anchor) for anchor in anchors)
        and name.startswith("test_")
        and name.endswith(".py")
    )


def module_name_for(rel_path: str) -> "str | None":
    """Dotted module name for a repo-relative source path, if it is one."""
    if not rel_path.endswith(".py"):
        return None
    trimmed = rel_path[: -len(".py")]
    # A project's own checks import under the namespace the engine loads
    # them in, not under their folder. Naming them by folder leaves every
    # test that imports one unreachable from the check it tests.
    if trimmed.startswith(_PROJECT_CHECKS_PREFIX):
        leaf = trimmed[len(_PROJECT_CHECKS_PREFIX) :]
        return f"{PROJECT_CHECKS_PACKAGE}.{leaf}" if leaf else None
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


def _string_path_references(tree: ast.AST) -> set[str]:
    """``.py`` path literals — full repo-relative paths and bare names.

    Resolved against the index's own file list by the caller, so a literal
    naming no real file is simply dropped rather than becoming an inert
    key.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        value = node.value.strip()
        if len(value) > 200:
            continue
        if _REPO_RELATIVE_PY.match(value):
            found.add(value)
    return found


@dataclass(frozen=True)
class ImportIndex:
    """Reverse import edges plus the module name of every source file."""

    importers: dict[str, set[str]]
    module_of: dict[str, str]


def direct_changed_tests(changed: Iterable[str], index: ImportIndex) -> frozenset[str]:
    """Modified or added test files that still exist in the tree.

    A changed test is definitionally impacted. Callers include this set
    before reachability runs, and keep it when a bounded run defers a
    near-total remainder.
    """
    return frozenset(
        rel for rel in changed if rel in index.module_of and is_test_file(rel)
    )


def direct_importer_tests(changed: Iterable[str], index: ImportIndex) -> frozenset[str]:
    """Tests that directly import a changed module, without transitive fanout."""
    modules = {index.module_of[path] for path in changed if path in index.module_of}
    return frozenset(
        importer
        for module in modules
        for importer in index.importers.get(module, ())
        if is_test_file(importer)
    )


def reachable_tests(changed: Sequence[str], index: ImportIndex) -> set[str] | None:
    """Test files reachable from *changed*, or None when nothing maps."""
    reached: set[str] = set(changed)
    frontier = [
        module for rel in changed if (module := index.module_of.get(rel)) is not None
    ]
    if not frontier:
        return None
    seen_modules = set(frontier)
    while frontier:
        module = frontier.pop()
        for importer in index.importers.get(module, ()):
            if importer in reached:
                continue
            reached.add(importer)
            importer_module = index.module_of.get(importer)
            if importer_module and importer_module not in seen_modules:
                seen_modules.add(importer_module)
                frontier.append(importer_module)
    # Keep deletions in analysis, but never pass removed tests to pytest.
    return {rel for rel in reached if rel in index.module_of and is_test_file(rel)}


def bounded_importer_tests(
    changed: Iterable[str],
    index: ImportIndex,
    *,
    total_files: int,
) -> frozenset[str]:
    """Keep tests behind importer branches that remain individually bounded."""
    paths = tuple(changed)
    tests = set(direct_importer_tests(paths, index))
    modules = {index.module_of[path] for path in paths if path in index.module_of}
    for module in modules:
        for importer in index.importers.get(module, ()):
            if is_test_file(importer):
                continue
            branch = reachable_tests((importer,), index) or set()
            if not is_effectively_full(len(branch), total_files):
                tests.update(branch)
    return frozenset(tests)


def build_import_index(repo_root: Path) -> ImportIndex:
    importers: dict[str, set[str]] = {}
    module_of: dict[str, str] = {}
    # Path literals resolve to modules only once every file is known, so
    # they are collected here and folded in after the scan.
    path_references: list[tuple[str, set[str]]] = []
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
        named_paths = _string_path_references(tree)
        if named_paths:
            path_references.append((rel, named_paths))
    by_file_name: dict[str, set[str]] = {}
    for rel in module_of:
        by_file_name.setdefault(rel.rsplit("/", 1)[-1], set()).add(rel)
    for rel, named_paths in path_references:
        for named in named_paths:
            referenced_module = _referenced_module(named, module_of, by_file_name)
            if referenced_module:
                importers.setdefault(referenced_module, set()).add(rel)
    return ImportIndex(importers=importers, module_of=module_of)


def _referenced_module(
    named: str,
    module_of: dict[str, str],
    by_file_name: dict[str, set[str]],
) -> "str | None":
    """The module one path literal names, or ``None`` when it names none.

    A bare file name resolves only when exactly one file carries it. The
    common ambiguous names — ``__init__.py``, ``conftest.py`` — would
    otherwise link one literal to every package in the repository, which
    is a widening rather than a reference.
    """
    module = module_of.get(named)
    if module is not None or "/" in named:
        return module
    candidates = by_file_name.get(named, set())
    if len(candidates) != 1:
        return None
    return module_of.get(next(iter(candidates)))


__all__ = [
    "ImportIndex",
    "TEST_ANCHORS",
    "bounded_importer_tests",
    "build_import_index",
    "direct_changed_tests",
    "direct_importer_tests",
    "is_test_file",
    "module_name_for",
    "reachable_tests",
]
