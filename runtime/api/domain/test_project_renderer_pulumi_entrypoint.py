"""Tests for the rendered Pulumi entrypoint import boundary."""

from __future__ import annotations

import ast

from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source


def test_environment_entrypoint_imports_stack_modules_inside_dispatch():
    entrypoint = _pack_program_source("__main__.py")
    tree = ast.parse(entrypoint.read_text())
    top_level_imports = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
    }

    assert not {
        "webapp_api_stack",
        "webapp_database_stack",
        "webapp_environment_stack",
        "webapp_runner_fleet_stack",
    } & top_level_imports


def test_environment_stack_never_imports_embedded_vps_stack():
    environment_stack = _pack_program_source("webapp_environment_stack.py")
    tree = ast.parse(environment_stack.read_text())
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert "webapp_vps_stack" not in imports
