"""Which module actually defines a name another module hands out.

Sibling of :mod:`yoke_core.tools._impacted_import_index`, which owns the
reverse import graph and folds these edges into it. Split out to keep
both files under the authored-file line cap.

A test rarely imports the file it exercises. It imports the surface that
file is reached through, and names the symbol: a health check is written
in one module, collected into a registry, re-exported by the runner, and
the test writes ``from pkg.runner import hc_thing``. Reading only module
edges, the test depends on the runner and the change three hops below it
is invisible — the test asserts the changed function's output and is
never selected for it.

Following the name instead of the module closes that gap exactly. The
chain above is explicit at every step, so ``hc_thing`` resolves from the
runner, through the registry, to the module that writes ``def hc_thing``,
and the test becomes a direct importer of it. Nothing else is pulled in:
the edge is the one symbol, not the runner's whole fan-in.

Resolution is conservative, because a test selector that over-selects
costs time while one that under-selects costs a green run on a broken
tree. A name this parser cannot follow — assembled by a loop, rebound at
runtime, re-exported from a module outside the tree — simply yields no
extra edge, leaving the module-level edges the index already has. A name
two star-imports could both supply yields both, since selecting one test
too many is the cheap mistake.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

#: Where a name came from: ``None`` for a binding written in the module
#: itself, or the ``(source module, name there)`` it was imported under.
Binding = "tuple[str, str] | None"


@dataclass
class ModuleSymbols:
    """The names a module hands out, and where each one last came from."""

    #: Local name -> its LAST module-level binding. Order matters: a
    #: module that defines a name and then imports one over it hands out
    #: the import, and the reverse hands out the definition, so the map
    #: keeps whichever statement ran last rather than both.
    bindings: dict = field(default_factory=dict)
    #: Modules whose whole public surface this module re-exports.
    star_sources: list[str] = field(default_factory=list)


def containing_package(rel: str, module: "str | None") -> str:
    """The package a file's relative imports resolve against.

    A package's ``__init__`` IS its package, so ``from .impl import x``
    there means ``pkg.impl``. Every other module resolves against its
    parent. Taking the parent in both cases silently walks one level too
    far up for every re-export a package front door performs, which is
    where library-shaped code puts most of them.
    """
    if not module:
        return ""
    if rel.endswith("/__init__.py") or rel == "__init__.py":
        return module
    return module.rsplit(".", 1)[0] if "." in module else ""


def module_symbols(tree: ast.AST, package: str) -> ModuleSymbols:
    """The symbol table for one parsed module.

    Only module-level bindings count. A name bound inside a function is
    not part of the surface another module can import, and treating it as
    one would attach edges to whichever file happened to reuse the name.
    """
    symbols = ModuleSymbols()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.bindings[node.name] = None
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _bound_names(target):
                    symbols.bindings[name] = None
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            for name in _bound_names(node.target):
                symbols.bindings[name] = None
        elif isinstance(node, ast.ImportFrom):
            _record_from_import(node, symbols, package)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # ``import pkg.mod as m`` binds ``m`` to that module; the
                # plain form binds the top package, which the module
                # graph already covers.
                if alias.asname:
                    symbols.bindings[alias.asname] = (alias.name, "")
    return symbols


def _bound_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in target.elts:
            names |= _bound_names(element)
        return names
    return set()


def _record_from_import(
    node: ast.ImportFrom, symbols: ModuleSymbols, package: str
) -> None:
    source = _absolute_source(node, package)
    if not source:
        # A relative import that walks above the known package root
        # names nothing this index can resolve; leave it alone.
        return
    for alias in node.names:
        if alias.name == "*":
            symbols.star_sources.append(source)
            continue
        # The alias is how this module hands the name out; the original
        # is what to look for upstream.
        symbols.bindings[alias.asname or alias.name] = (source, alias.name)


def _absolute_source(node: ast.ImportFrom, package: str) -> str:
    base = node.module or ""
    if not node.level:
        return base
    ancestor = package
    for _ in range(node.level - 1):
        ancestor = ancestor.rsplit(".", 1)[0] if "." in ancestor else ""
    if not ancestor:
        return base
    return f"{ancestor}.{base}" if base else ancestor


def imported_symbol_references(tree: ast.AST, package: str) -> set[tuple[str, str]]:
    """``(module, name)`` pairs a file imports by name, at any depth.

    Unlike the defining side, this walks the whole tree: a test that
    imports the surface it exercises inside the test function is the
    ordinary shape, not an exception.
    """
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = _absolute_source(node, package)
        if not source:
            continue
        for alias in node.names:
            if alias.name != "*":
                found.add((source, alias.name))
    return found


class SymbolResolver:
    """Follows an imported name to the module or modules defining it."""

    def __init__(self, symbols: dict[str, ModuleSymbols]) -> None:
        self._symbols = symbols
        self._cache: dict[tuple[str, str], frozenset[str]] = {}

    def defining_modules(self, source: str, name: str) -> frozenset[str]:
        """Modules that define *name* as re-exported by *source*.

        Empty when the chain leaves the tree, dead-ends, or is built by
        anything this parser does not read — the conservative answer,
        which adds no edge and changes no existing one.
        """
        return self._resolve(source, name, set())

    def _resolve(
        self, source: str, name: str, active: set[tuple[str, str]]
    ) -> frozenset[str]:
        key = (source, name)
        top_level = not active
        if top_level and key in self._cache:
            return self._cache[key]
        if key in active:
            # A re-export cycle: two modules handing the same name back
            # and forth resolve to whatever else the walk found.
            return frozenset()
        symbols = self._symbols.get(source)
        if symbols is None:
            return frozenset()
        active.add(key)
        try:
            found = self._walk(symbols, source, name, active)
        finally:
            active.discard(key)
        # Only a query that started from nothing is cached. A result
        # reached underneath another one may have been cut short by that
        # walk's own cycle guard, and storing it would let the order
        # queries happen to arrive in decide a later answer.
        if top_level:
            self._cache[key] = found
        return found

    def _walk(
        self,
        symbols: ModuleSymbols,
        source: str,
        name: str,
        active: set[tuple[str, str]],
    ) -> frozenset[str]:
        if name in symbols.bindings:
            upstream = symbols.bindings[name]
            if upstream is None:
                return frozenset({source})
            origin, original = upstream
            if not original:
                # ``import pkg.mod as m`` — the alias IS the module.
                return frozenset({origin}) if origin in self._symbols else frozenset()
            return self._resolve(origin, original, active)
        # Sorted so a name two star-imports could supply resolves the
        # same way on every run.
        found: set[str] = set()
        for star in sorted(symbols.star_sources):
            found |= self._resolve(star, name, active)
        return frozenset(found)


def reexport_edges(
    referenced_names: dict[str, set[tuple[str, str]]],
    symbols: dict[str, ModuleSymbols],
) -> dict[str, set[str]]:
    """Reverse edges from each defining module to the files naming it.

    *referenced_names* maps a repo-relative file to the ``(module, name)``
    pairs it imports by name. The result is keyed by defining module, in
    the shape the import index merges into its own ``importers`` map.
    """
    resolver = SymbolResolver(symbols)
    edges: dict[str, set[str]] = {}
    for rel, pairs in referenced_names.items():
        for source, name in pairs:
            for defining in resolver.defining_modules(source, name):
                if defining != source:
                    edges.setdefault(defining, set()).add(rel)
    return edges


__all__ = [
    "ModuleSymbols",
    "SymbolResolver",
    "containing_package",
    "imported_symbol_references",
    "module_symbols",
    "reexport_edges",
]
