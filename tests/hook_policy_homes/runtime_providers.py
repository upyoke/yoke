"""Resolve runtime interface values from the checkout's declared providers."""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
from typing import Callable

from yoke_contracts.runtime_adapter_sources import source_providers


@lru_cache(maxsize=None)
def providers(repo: Path) -> dict[str, str]:
    return source_providers(repo)


def provider_for_call(mod, node: ast.AST, repo: Path, module: Callable) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return None
    alias = mod.aliases.get(node.func.id)
    if alias is None or not alias[0].startswith("yoke_contracts.runtime_ports."):
        return None
    owner = module(alias[0])
    getter = owner.defs.get(alias[1]) if owner else None
    if getter is None:
        raise ValueError(f"Runtime getter not found: {alias}")
    loads = [
        call for call in ast.walk(getter)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        and call.func.id == "load_port"
    ]
    if len(loads) != 1 or not loads[0].args or not isinstance(loads[0].args[0], ast.Constant):
        raise ValueError(f"Runtime getter has no single declared provider: {alias}")
    name = loads[0].args[0].value
    target = providers(repo).get(name)
    if target is None or module(target) is None:
        raise ValueError(f"Runtime provider not found: {name!r}")
    return target


def bindings(mod, tree: ast.AST, repo: Path, module: Callable) -> dict[str, str]:
    result: dict[str, str] = {}
    # Module assignments are visible inside functions; function-local bindings
    # override them. Keep other functions' assignments out of this scope.
    nodes = [*mod.tree.body, *ast.walk(tree)]
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = provider_for_call(mod, node.value, repo, module)
            if target is not None:
                names = node.targets if isinstance(node, ast.Assign) else [node.target]
                result.update((name.id, target) for name in names if isinstance(name, ast.Name))
    return result


def targets(mod, node: ast.AST, bound: dict[str, str], repo: Path, module: Callable):
    if not isinstance(node, ast.Attribute):
        return
    target = (
        bound.get(node.value.id) if isinstance(node.value, ast.Name)
        else provider_for_call(mod, node.value, repo, module)
    )
    if target is not None:
        yield target, node.attr
