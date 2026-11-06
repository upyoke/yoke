"""The domain merge contract must remain independent of merge orchestration."""

from __future__ import annotations

import ast
from pathlib import Path

import yoke_core.domain


def test_domain_does_not_import_merge_worktree_engines() -> None:
    root = Path(yoke_core.domain.__file__).parent
    forbidden = []
    for source in root.rglob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
            elif (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "__import__"
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            ):
                modules = [node.args[0].value]
            for module in modules:
                if module.startswith("yoke_core.engines.merge_worktree"):
                    forbidden.append(f"{source.relative_to(root)}:{node.lineno}: {module}")
    assert not forbidden, "Domain imported merge orchestration:\n" + "\n".join(forbidden)
