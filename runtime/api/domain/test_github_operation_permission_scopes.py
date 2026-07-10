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
_PRIVILEGED_SCOPE_NAMES = frozenset({
    "GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS",
    "GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS",
    "GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS",
    "GITHUB_REPOSITORY_HOOKS_WRITE_PERMISSION_LEVELS",
    "RUNNERS_STATUS_PERMISSION_LEVELS",
})
_PRIVILEGED_PERMISSION_KEYS = frozenset({
    "administration",
    "repository_hooks",
})
_PRIVILEGED_PERMISSION_KEY_NAMES = {
    "ADMINISTRATION_PERMISSION": "administration",
    "REPOSITORY_HOOKS_PERMISSION": "repository_hooks",
}
_PRIVILEGED_SCOPE_ALLOWLIST = frozenset({
    (
        "packages/yoke-core/src/yoke_core/domain/bootstrap_project_setup.py",
        "run_setup",
        "GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS",
    ),
    (
        "packages/yoke-core/src/yoke_core/domain/handlers/"
        "github_actions_runners.py",
        "handle_runners_status",
        "RUNNERS_STATUS_PERMISSION_LEVELS",
    ),
    (
        "packages/yoke-core/src/yoke_core/engines/"
        "doctor_hc_branch_protection.py",
        "hc_branch_protection_required_check",
        "GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS",
    ),
})
_DIRECT_MINTER_ALLOWLIST = frozenset({
    (
        "packages/yoke-core/src/yoke_core/domain/"
        "github_app_installation_tokens.py",
        "get_or_mint",
    ),
})
_MINTER_IMPORT_ALLOWLIST = frozenset({
    "packages/yoke-core/src/yoke_core/tools/runner_fleet_exec.py",
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


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for imported in node.names:
            aliases[imported.asname or imported.name] = imported.name
    return aliases


def _direct_assignments(scope: ast.AST) -> dict[str, ast.AST]:
    assignments: dict[str, ast.AST] = {}
    for statement in getattr(scope, "body", []):
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name,
        ):
            if statement.value is not None:
                assignments[statement.target.id] = statement.value
    return assignments


def _privileged_markers(
    expression: ast.AST,
    *,
    scope: ast.AST,
    tree: ast.Module,
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    if isinstance(expression, ast.Constant):
        value = expression.value
        return (
            {f"literal:{value}"}
            if isinstance(value, str) and value in _PRIVILEGED_PERMISSION_KEYS
            else set()
        )
    if isinstance(expression, ast.Name):
        aliases = _import_aliases(tree)
        canonical = aliases.get(expression.id, expression.id)
        if canonical in _PRIVILEGED_SCOPE_NAMES:
            return {canonical}
        if canonical in _PRIVILEGED_PERMISSION_KEY_NAMES:
            return {
                "constant:"
                + _PRIVILEGED_PERMISSION_KEY_NAMES[canonical]
            }
        if expression.id in seen:
            return set()
        assignments = {
            **_direct_assignments(tree),
            **_direct_assignments(scope),
        }
        assigned = assignments.get(expression.id)
        if assigned is None:
            return set()
        return _privileged_markers(
            assigned,
            scope=scope,
            tree=tree,
            seen=seen | {expression.id},
        )
    if isinstance(expression, ast.Attribute):
        if expression.attr in _PRIVILEGED_SCOPE_NAMES:
            return {expression.attr}
        if expression.attr in _PRIVILEGED_PERMISSION_KEY_NAMES:
            return {
                "constant:"
                + _PRIVILEGED_PERMISSION_KEY_NAMES[expression.attr]
            }
    if isinstance(expression, ast.Call):
        markers = {
            f"literal:{keyword.arg}"
            for keyword in expression.keywords
            if keyword.arg in _PRIVILEGED_PERMISSION_KEYS
        }
    else:
        markers = set()
    for child in ast.iter_child_nodes(expression):
        markers.update(_privileged_markers(
            child, scope=scope, tree=tree, seen=seen,
        ))
    return markers


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


def test_privileged_operation_scopes_and_aliases_are_allowlisted() -> None:
    observed: set[tuple[str, str, str]] = set()
    privileged_helpers = _EXPLICIT_SCOPE_HELPERS | {
        "resolve_project_github_auth",
    }
    for path, tree in _source_modules():
        relative = str(path.relative_to(_REPO_ROOT))
        parent_by_node = _parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if _call_name(call) not in privileged_helpers:
                continue
            required = next(
                (
                    keyword.value
                    for keyword in call.keywords
                    if keyword.arg == "required_permissions"
                ),
                None,
            )
            scope = _enclosing_scope(tree, call, parent_by_node)
            if required is None:
                continue
            for marker in _privileged_markers(
                required, scope=scope, tree=tree,
            ):
                observed.add((
                    relative,
                    getattr(scope, "name", "<module>"),
                    marker,
                ))

    assert observed == _PRIVILEGED_SCOPE_ALLOWLIST


def test_privileged_scope_detection_covers_alias_and_inline_bypasses() -> None:
    tree = ast.parse(
        "import contract as permission_contract\n"
        "from contract import GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS\n"
        "from contract import ADMINISTRATION_PERMISSION as ADMIN_KEY\n"
        "ADMIN = GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS\n"
        "def named():\n"
        "    resolve_auth(required_permissions=ADMIN)\n"
        "def inline():\n"
        "    resolve_auth(required_permissions={'administration': 'read'})\n"
        "def constant_key():\n"
        "    resolve_auth(required_permissions={ADMIN_KEY: 'read'})\n"
        "def module_scope():\n"
        "    resolve_auth(required_permissions="
        "permission_contract.GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS)\n"
        "def module_key():\n"
        "    resolve_auth(required_permissions={"
        "permission_contract.REPOSITORY_HOOKS_PERMISSION: 'write'})\n"
    )
    parent_by_node = _parent_map(tree)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    observed = {}
    for call in calls:
        scope = _enclosing_scope(tree, call, parent_by_node)
        required = next(
            keyword.value for keyword in call.keywords
            if keyword.arg == "required_permissions"
        )
        observed[getattr(scope, "name", "<module>")] = _privileged_markers(
            required, scope=scope, tree=tree,
        )
    assert observed == {
        "named": {"GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS"},
        "inline": {"literal:administration"},
        "constant_key": {"constant:administration"},
        "module_scope": {"GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS"},
        "module_key": {"constant:repository_hooks"},
    }


def test_direct_installation_token_minters_and_imports_are_allowlisted() -> None:
    direct_calls: set[tuple[str, str]] = set()
    minter_imports: set[str] = set()
    for path, tree in _source_modules():
        relative = str(path.relative_to(_REPO_ROOT))
        aliases = _import_aliases(tree)
        if "mint_installation_token" in aliases.values():
            minter_imports.add(relative)
        parent_by_node = _parent_map(tree)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            canonical = aliases.get(_call_name(call), _call_name(call))
            if canonical != "mint_installation_token":
                continue
            scope = _enclosing_scope(tree, call, parent_by_node)
            direct_calls.add((relative, getattr(scope, "name", "<module>")))

    assert direct_calls == _DIRECT_MINTER_ALLOWLIST
    assert minter_imports == _MINTER_IMPORT_ALLOWLIST
