"""Import-edge scanner for the CLI product-boundary inventory."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_ENGINE_IMPORT_BOUNDARY_ROOTS = frozenset(
    {"psycopg", "psycopg2", "runtime", "yoke_core"}
)


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    kind: str
    classification: str = ""
    rationale: str = ""


def load_boundary_facts(
    root: Path | None,
) -> tuple[frozenset[str], dict[tuple[str, str], tuple[str, str]]]:
    """Load import roots and sanctioned dynamic edges from the guard test."""
    if root is None:
        return _ENGINE_IMPORT_BOUNDARY_ROOTS, {}
    path = root / "runtime" / "api" / "test_installer_package_boundaries.py"
    if not path.is_file():
        return _ENGINE_IMPORT_BOUNDARY_ROOTS, {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return _ENGINE_IMPORT_BOUNDARY_ROOTS, {}
    boundary_roots = _ENGINE_IMPORT_BOUNDARY_ROOTS
    dynamic: dict[tuple[str, str], tuple[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
        if "ENGINE_IMPORT_BOUNDARY_ROOTS" in names:
            boundary_roots = frozenset(str(item) for item in value)
        if "ALLOWED_DYNAMIC_AUTHORITY_IMPORTS" in names:
            dynamic = {
                (str(rel), str(module)): (str(kind), str(reason))
                for (rel, module), (kind, reason) in value.items()
            }
    return boundary_roots, dynamic


def scan_import_edges(
    package_root: Path,
    repo_root: Path | None,
    boundary_roots: frozenset[str],
    allowlist: Mapping[tuple[str, str], tuple[str, str]],
) -> dict[str, tuple[ImportEdge, ...]]:
    """Return engine-authority import edges keyed by source path."""
    out: dict[str, list[ImportEdge]] = {}
    for path in sorted(package_root.rglob("*.py")):
        rel = _relative_source(path, repo_root, package_root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            found = _edges_from_node(
                node, rel, boundary_roots, allowlist,
            )
            if found:
                out.setdefault(rel, []).extend(found)
    return {
        source: tuple(sorted(
            items,
            key=lambda edge: (
                edge.kind,
                edge.target,
                edge.classification,
                edge.rationale,
            ),
        ))
        for source, items in out.items()
    }


def repo_root_from_package(package_root: Path) -> Path | None:
    for parent in package_root.parents:
        if (parent / "packages" / "yoke-cli" / "src" / "yoke_cli").is_dir():
            return parent
    return None


def module_source(
    module: str, package_root: Path, repo_root: Path | None,
) -> str:
    if not module.startswith("yoke_cli."):
        return module
    path = package_root.joinpath(*module.split(".")[1:]).with_suffix(".py")
    if not path.is_file():
        path = package_root.joinpath(*module.split(".")[1:], "__init__.py")
    return _relative_source(path, repo_root, package_root)


def module_name_from_source(source: str) -> str:
    marker = "packages/yoke-cli/src/"
    if source.startswith(marker):
        source = source[len(marker):]
    if source.endswith("/__init__.py"):
        source = source[:-12]
    elif source.endswith(".py"):
        source = source[:-3]
    return source.replace("/", ".")


def _edges_from_node(
    node: ast.AST,
    rel: str,
    boundary_roots: frozenset[str],
    allowlist: Mapping[tuple[str, str], tuple[str, str]],
) -> tuple[ImportEdge, ...]:
    if isinstance(node, ast.Import):
        return tuple(
            ImportEdge(
                rel,
                alias.name,
                "static",
                "static_authority_import",
                "direct authority import",
            )
            for alias in node.names
            if _root(alias.name) in boundary_roots
        )
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if _root(module) in boundary_roots:
            return (ImportEdge(
                rel,
                module,
                "static",
                "static_authority_import",
                "direct authority import",
            ),)
        return ()
    if (
        isinstance(node, ast.Call)
        and _call_name(node)
        in {"__import__", "import_module", "importlib.import_module"}
    ):
        module = _literal_module_arg(node)
        if module and _root(module) in boundary_roots:
            kind, reason = allowlist.get(
                (rel, module),
                ("unclassified_dynamic_authority_import", ""),
            )
            return (ImportEdge(rel, module, "dynamic", kind, reason),)
    return ()


def _relative_source(
    path: Path, repo_root: Path | None, package_root: Path,
) -> str:
    if repo_root:
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            pass
    try:
        return path.relative_to(package_root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _root(module: str) -> str:
    return module.split(".", 1)[0]


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if not isinstance(func, ast.Attribute):
        return ""
    parts = [func.attr]
    current = func.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _literal_module_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


__all__ = [
    "ImportEdge",
    "load_boundary_facts",
    "module_name_from_source",
    "module_source",
    "repo_root_from_package",
    "scan_import_edges",
]
