"""Static guard for request-scoped GitHub App operation tokens."""

from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _REPO_ROOT / "packages/yoke-core/src/yoke_core"
_EXPLICIT_SCOPE_HELPERS = frozenset({
    "_target_for",
    "_validate_and_resolve",
    "_validate_and_resolve_auth",
    "graphql_query",
    "resolve_auth",
    "resolve_target",
    "resolve_token",
})


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _has_required_permissions(call: ast.Call) -> bool:
    return any(keyword.arg == "required_permissions" for keyword in call.keywords)


def _assigned_names(scope: ast.AST, call: ast.Call) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None or call not in ast.walk(value):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _uses_token(scope: ast.AST, call: ast.Call) -> bool:
    parent_by_node = {
        child: parent
        for parent in ast.walk(scope)
        for child in ast.iter_child_nodes(parent)
    }
    parent = parent_by_node.get(call)
    if isinstance(parent, ast.Attribute) and parent.attr == "token":
        return True
    assigned = _assigned_names(scope, call)
    return any(
        isinstance(node, ast.Attribute)
        and node.attr == "token"
        and isinstance(node.value, ast.Name)
        and node.value.id in assigned
        for node in ast.walk(scope)
    )


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_scope(
    tree: ast.Module,
    call: ast.Call,
    parent_by_node: dict[ast.AST, ast.AST],
) -> ast.AST:
    node: ast.AST = call
    while node in parent_by_node:
        node = parent_by_node[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return tree


def _source_modules():
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_token_consumers_never_use_implicit_installation_scope() -> None:
    failures: list[str] = []
    for path, tree in _source_modules():
        relative = path.relative_to(_REPO_ROOT)
        parent_by_node = _parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if _call_name(call) != "resolve_project_github_auth":
                continue
            scope = _enclosing_scope(tree, call, parent_by_node)
            if _uses_token(scope, call) and not _has_required_permissions(call):
                failures.append(f"{relative}:{call.lineno}")
    assert failures == [], "implicit token scope at " + ", ".join(sorted(set(failures)))


def test_token_resolving_helpers_require_operation_scope_at_each_call() -> None:
    failures: list[str] = []
    for path, tree in _source_modules():
        relative = path.relative_to(_REPO_ROOT)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if _call_name(call) not in _EXPLICIT_SCOPE_HELPERS:
                continue
            if not _has_required_permissions(call):
                failures.append(f"{relative}:{call.lineno}:{_call_name(call)}")
    assert failures == [], "helper call omitted operation scope at " + ", ".join(failures)
