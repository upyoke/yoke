"""Pytest fixture facts gathered during the import-index scan.

Tests reach conftest fixtures by parameter name, never by import, so the
import graph cannot say which tests a conftest change touches. This module
records the facts that can: each fixture owner's fixtures, hooks, and
imports, and the names every test module and conftest asks for. A fixture
owner is a ``conftest.py`` or a module a conftest loads through
``pytest_plugins``; its scope is the conftest's directory.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

_CONFTEST = "conftest.py"
_HOOK_PREFIX = "pytest_"
_PLUGINS_NAME = "pytest_plugins"
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.\w+)+$")
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Fixture:
    autouse: bool
    #: Fixture names the fixture requests as parameters.
    params: frozenset[str]
    #: Names, dotted string literals (with every module prefix), and
    #: modules imported inside the body: what a change can reach it through.
    refs: frozenset[str]


@dataclass(frozen=True)
class FixtureOwner:
    path: str
    #: Directory prefix whose tests see this owner ("" for the repo root).
    scope: str
    fixtures: Mapping[str, Fixture]
    #: Everything the ``pytest_*`` hooks reference; hooks shape every test.
    hook_refs: frozenset[str]
    has_hooks: bool
    #: References made by module-level statements, which run at collection.
    module_refs: frozenset[str]
    #: Module-level import bindings: local name -> modules it may name.
    bindings: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class FixtureGraph:
    owners: Mapping[str, FixtureOwner] = field(default_factory=dict)
    #: Test modules and conftests -> every name they could request.
    uses: Mapping[str, frozenset[str]] = field(default_factory=dict)


def _dotted_prefixes(value: str) -> set[str]:
    parts = value.split(".")
    return {".".join(parts[:end]) for end in range(2, len(parts) + 1)}


def _absolute(node: ast.ImportFrom, package: str) -> str:
    if not node.level:
        return node.module or ""
    base = package
    for _ in range(node.level - 1):
        base = base.rsplit(".", 1)[0] if "." in base else ""
    return f"{base}.{node.module}" if node.module and base else (node.module or base)


def _references(nodes: Iterable[ast.AST], package: str) -> frozenset[str]:
    found: set[str] = set()
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if len(value) <= 200 and _DOTTED.match(value):
                    found.update(_dotted_prefixes(value))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found.update({alias.name, *_dotted_prefixes(alias.name)})
            elif isinstance(node, ast.ImportFrom):
                base = _absolute(node, package)
                found.add(base)
                found.update(f"{base}.{alias.name}" for alias in node.names)
    return frozenset(found)


def _fixture_decorator(node: ast.AST) -> "tuple[bool, str] | None":
    """``(autouse, name override)`` when *node* is a fixture decorator."""
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call else node
    name = (
        target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
    )
    if name != "fixture":
        return None
    autouse, rename = False, ""
    for keyword in call.keywords if call else ():
        if not isinstance(keyword.value, ast.Constant):
            continue
        if keyword.arg == "autouse":
            autouse = bool(keyword.value.value)
        elif keyword.arg == "name" and isinstance(keyword.value.value, str):
            rename = keyword.value.value
    return autouse, rename


def _params(node: ast.AST) -> frozenset[str]:
    args = node.args  # type: ignore[attr-defined]
    return frozenset(
        arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)
    )


def _bindings(tree: ast.Module, package: str) -> dict[str, frozenset[str]]:
    bound: dict[str, set[str]] = {}
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bound.setdefault(local, set()).add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node, package)
            for alias in node.names:
                local = alias.asname or alias.name
                bound.setdefault(local, set()).update({base, f"{base}.{alias.name}"})
        else:
            pending.extend(ast.iter_child_nodes(node))
    return {name: frozenset(modules) for name, modules in bound.items()}


def _plugin_modules(tree: ast.Module) -> tuple[str, ...]:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else ()
        if any(getattr(t, "id", "") == _PLUGINS_NAME for t in targets):
            value = node.value  # type: ignore[union-attr]
            items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
            return tuple(
                item.value
                for item in items
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return ()


def _requested_names(tree: ast.Module) -> frozenset[str]:
    """Parameter names plus identifier-shaped strings (``usefixtures``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTIONS):
            names.update(_params(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _IDENTIFIER.match(node.value):
                names.add(node.value)
    return frozenset(names)


class FixtureGraphBuilder:
    """Collects owner candidates and requested names over one scan."""

    def __init__(self) -> None:
        self._candidates: dict[str, tuple[ast.Module, str]] = {}
        self._plugins: dict[str, tuple[str, ...]] = {}
        self._uses: dict[str, frozenset[str]] = {}

    def observe(
        self, rel: str, module: "str | None", tree: ast.Module, *, is_test: bool
    ) -> None:
        is_conftest = PurePosixPath(rel).name == _CONFTEST
        if is_test or is_conftest:
            self._uses[rel] = _requested_names(tree)
        if is_test:
            return
        package = module.rsplit(".", 1)[0] if module and "." in module else ""
        if is_conftest:
            self._plugins[rel] = _plugin_modules(tree)
            self._candidates[rel] = (tree, package)
            return
        defines = any(
            isinstance(node, _FUNCTIONS)
            and (
                node.name.startswith(_HOOK_PREFIX)
                or any(_fixture_decorator(d) for d in node.decorator_list)
            )
            for node in tree.body
        )
        if defines:
            self._candidates[rel] = (tree, package)

    def build(self, module_of: Mapping[str, str]) -> FixtureGraph:
        path_of = {module: rel for rel, module in module_of.items()}
        owners: dict[str, FixtureOwner] = {}
        for conftest, plugins in self._plugins.items():
            parent = str(PurePosixPath(conftest).parent)
            scope = "" if parent == "." else f"{parent}/"
            for rel in (conftest, *(path_of.get(p, "") for p in plugins)):
                if rel in self._candidates and rel not in owners:
                    owners[rel] = _owner(rel, scope, *self._candidates[rel])
        return FixtureGraph(owners=owners, uses=self._uses)


def _owner(rel: str, scope: str, tree: ast.Module, package: str) -> FixtureOwner:
    fixtures: dict[str, Fixture] = {}
    hooks: list[ast.AST] = []
    module_level: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or _plugin_modules(
            ast.Module(body=[node], type_ignores=[])
        ):
            # A plugin is its own owner; naming it is not a reference.
            continue
        if not isinstance(node, _FUNCTIONS):
            module_level.append(node)
            continue
        decorated = [d for d in map(_fixture_decorator, node.decorator_list) if d]
        if decorated:
            autouse, rename = decorated[0]
            fixtures[rename or node.name] = Fixture(
                autouse=autouse,
                params=_params(node),
                refs=_references([node], package),
            )
        elif node.name.startswith(_HOOK_PREFIX):
            hooks.append(node)
    return FixtureOwner(
        path=rel,
        scope=scope,
        fixtures=fixtures,
        hook_refs=_references(hooks, package),
        has_hooks=bool(hooks),
        module_refs=_references(module_level, package),
        bindings=_bindings(tree, package),
    )


__all__ = ["Fixture", "FixtureGraph", "FixtureGraphBuilder", "FixtureOwner"]
