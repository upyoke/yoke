"""Detect dedicated tests whose permanent migration entry was squashed."""

from __future__ import annotations

import ast
from pathlib import Path

MODULE_PREFIX = "yoke_core.domain.migrations."
ENTRY_SELECTORS = {"ENTRY_NAME", "_ENTRY_NAME", "ENTRY_SLUG", "_ENTRY_SLUG"}


def _string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string(node.left), _string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def missing_test_entries(source: str, history_names: set[str]) -> set[str]:
    """Check import references and explicit history-loader selectors.

    Plain historical names in engine fixtures are data, not module references.
    Slug selectors support dedicated tests that use the production history loader.
    """
    missing = set()
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        value = _string(node)
        if value is not None and not isinstance(parents.get(node), ast.BinOp):
            if value.startswith(MODULE_PREFIX):
                name = value.removeprefix(MODULE_PREFIX)
                if name[:1].isdigit() and name not in history_names:
                    missing.add(name)
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not any(isinstance(t, ast.Name) and t.id in ENTRY_SELECTORS for t in node.targets):
            continue
        selector = node.value.value
        if not isinstance(selector, str):
            continue
        if not any(name == selector or name.endswith("_" + selector) for name in history_names):
            missing.add(selector)
    return missing


def obsolete_dedicated_tests(directory: Path, history_names: set[str]) -> dict[str, set[str]]:
    return {
        str(path.relative_to(directory)): missing
        for path in directory.rglob("test_*.py")
        if (missing := missing_test_entries(path.read_text(), history_names))
    }
