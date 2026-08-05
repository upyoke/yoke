"""Conservative classifier for read-only ``python -c`` import probes.

The agent-surface guard protects mutation paths, not source inspection.  This
module recognizes import/constant inspection and calls whose names explicitly
describe reads.  Unknown calls and every mutation-shaped call remain denied.
"""

from __future__ import annotations

import ast


_SAFE_BUILTINS = {
    "all", "any", "bool", "dict", "enumerate", "frozenset", "getattr",
    "hasattr", "isinstance", "len", "list", "max", "min", "print",
    "repr", "set", "sorted", "str", "sum", "tuple", "type", "vars",
}
_READ_PREFIXES = (
    "compare_", "compute_", "detect_", "discover_", "extract_", "fetch_",
    "find_", "get_", "inspect_", "list_", "load_", "parse_", "read_",
    "resolve_", "scan_", "validate_",
)
_MUTATION_WORDS = (
    "append", "apply", "archive", "commit", "create", "delete", "deploy",
    "dispatch", "drop", "emit", "execute", "insert", "merge", "mkdir",
    "mutate", "publish", "remove", "replace", "run", "send", "set",
    "start", "touch", "transition", "unlink", "update", "write",
)


def _call_name(node: ast.Call) -> str:
    current: ast.AST = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts)).lower()


def _has_mutation_word(name: str) -> bool:
    parts = name.lower().replace(".", "_").split("_")
    return any(word in parts for word in _MUTATION_WORDS)


def _is_read_call(node: ast.Call) -> bool:
    name = _call_name(node)
    leaf = name.rsplit(".", 1)[-1]
    if leaf in _SAFE_BUILTINS:
        return True
    if _has_mutation_word(leaf):
        return False
    return leaf.startswith(_READ_PREFIXES) or leaf.endswith("_digest")


def _is_read_symbol(name: str) -> bool:
    leaf = name.rsplit(".", 1)[-1]
    if leaf.isupper():
        return True
    if _has_mutation_word(leaf):
        return False
    lowered = leaf.lower()
    return lowered.startswith(_READ_PREFIXES) or lowered.endswith("_digest")


def is_read_only_import_probe(body: str) -> bool:
    """Return whether *body* is an inspection-only import one-liner."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False
    if any(isinstance(node, (ast.Delete, ast.Global, ast.Nonlocal))
           for node in ast.walk(tree)):
        return False
    imported_symbols: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_symbols.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_symbols.extend(alias.name for alias in node.names)
    if not imported_symbols or not all(
        _is_read_symbol(name) for name in imported_symbols
    ):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and not _is_read_call(node):
            return False
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            return False
    return True
