"""Project Structure modules must initialize independently in fresh processes."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", [
    "project_structure", "project_structure_write", "project_structure_validation",
    "project_structure_seeds", "project_structure_cli", "workflow_project_defaults",
])
def test_project_structure_import_orders(first):
    modules = [first, "project_structure", "project_structure_write",
               "project_structure_validation", "project_structure_seeds",
               "project_structure_cli", "workflow_project_defaults"]
    code = "\n".join(f"import yoke_core.domain.{module}" for module in modules)
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_project_structure_module_cli():
    result = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.project_structure", "family-list"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "deploy_defaults" in result.stdout
