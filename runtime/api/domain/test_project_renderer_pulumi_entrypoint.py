"""Tests for the rendered Pulumi entrypoint import boundary."""

from __future__ import annotations

import ast
from pathlib import Path


def test_environment_entrypoint_imports_stack_modules_inside_dispatch():
    repo_root = Path(__file__).resolve().parents[3]
    entrypoint = repo_root.joinpath(
        "templates", "webapp", "infra", "__main__.py",
    )
    tree = ast.parse(entrypoint.read_text())
    top_level_imports = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
    }

    assert not {
        "webapp_api_stack",
        "webapp_database_stack",
        "webapp_environment_stack",
    } & top_level_imports
