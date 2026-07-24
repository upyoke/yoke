"""Guard engine import boundaries for the client packages.

The engine ships beside the clients, but the active connection decides whether
it runs: HTTPS relays to the server, non-prod local Postgres dispatches in
process, and prod-flagged Postgres stays operator-only. Client packages cannot
take static authority over engine/runtime/database modules before that transport
decision. Dynamic imports remain limited to the classified lanes in
:mod:`runtime.api.dynamic_authority_import_allowlist`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from runtime.api.dynamic_authority_import_allowlist import (
    ALLOWED_DYNAMIC_AUTHORITY_IMPORTS,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOTS = (
    ROOT / "packages" / "yoke-cli" / "src" / "yoke_cli",
    ROOT / "packages" / "yoke-contracts" / "src" / "yoke_contracts",
    ROOT / "packages" / "yoke-harness" / "src" / "yoke_harness",
)
ENGINE_IMPORT_BOUNDARY_ROOTS = frozenset(
    {"psycopg", "psycopg2", "runtime", "yoke_core"}
)


def _root_name(module: str) -> str:
    return module.split(".", 1)[0]


def _iter_python_files() -> list[Path]:
    paths: list[Path] = []
    for package_root in PACKAGE_ROOTS:
        paths.extend(sorted(package_root.rglob("*.py")))
    return paths


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if not isinstance(func, ast.Attribute):
        return ""
    parts = [func.attr]
    cur = func.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _literal_module_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def test_cli_and_contract_packages_do_not_take_direct_core_imports():
    violations: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _root_name(alias.name) in ENGINE_IMPORT_BOUNDARY_ROOTS:
                        violations.append(f"{rel}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _root_name(module) in ENGINE_IMPORT_BOUNDARY_ROOTS:
                    violations.append(f"{rel}:{node.lineno}: from {module} import ...")
    assert violations == []


def test_dynamic_authority_imports_are_classified_and_bounded():
    observed: set[tuple[str, str]] = set()
    violations: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in {
                "__import__",
                "import_module",
                "importlib.import_module",
            }:
                continue
            module = _literal_module_arg(node)
            if module is None or _root_name(module) not in ENGINE_IMPORT_BOUNDARY_ROOTS:
                continue
            key = (rel, module)
            observed.add(key)
            if key not in ALLOWED_DYNAMIC_AUTHORITY_IMPORTS:
                violations.append(f"{rel}:{node.lineno}: {module}")
    stale_allowlist = sorted(
        f"{rel}: {module}"
        for rel, module in set(ALLOWED_DYNAMIC_AUTHORITY_IMPORTS) - observed
    )
    assert violations == []
    assert stale_allowlist == []
    for classification, rationale in ALLOWED_DYNAMIC_AUTHORITY_IMPORTS.values():
        assert classification
        assert rationale
