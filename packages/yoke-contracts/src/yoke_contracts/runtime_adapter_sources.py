"""Pure source metadata for runtime interface providers and references."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


def source_providers(repo: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted((repo / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        entries = data.get("project", {}).get("entry-points", {}).get("yoke.runtime", {})
        for name, target in entries.items():
            if name in result or not isinstance(target, str) or ":" in target:
                raise ValueError(f"Invalid or duplicate runtime provider {name!r}: {path}")
            result[name] = target
    return result



def runtime_references(tree: ast.AST, declared: dict[str, str]) -> set[str]:
    """Provider modules named by literal interface loader calls."""
    result = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "load_port" and node.args
                and isinstance(node.args[0], ast.Constant)):
            name = node.args[0].value
            if name not in declared:
                raise ValueError(f"Runtime provider not found: {name!r}")
            result.add(declared[name])
    return result
