# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import subprocess

import sys

from pathlib import Path

import pytest

from yoke_core.tools import (
    _source_pythonpath,
    source_dev_run,
    source_dev_scanner,
    watch_qa_case,
)

from runtime.api.source_pythonpath_test_helpers import provision_stub_environment

from yoke_core.domain.qa_environment_declaration import TestEnvironmentDeclaration

LANE_MARKER = "child-ran-from"

STUB_CLI_MAIN = f'''
import sys
from pathlib import Path

if __name__ == "__main__":
    print("{LANE_MARKER}", Path(__file__).resolve())
    print("args", " ".join(sys.argv[1:]))
'''


def _stub_source_tree(root: Path) -> Path:
    """Materialize a Yoke-shaped checkout whose CLI reports its own origin."""
    for relative in _source_pythonpath.PACKAGE_SRC_RELS:
        package = Path(relative).parent.name.replace("-", "_")
        package_dir = root / relative / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").touch()
    (root / "runtime").mkdir()
    (root / "runtime" / "__init__.py").touch()
    provision_stub_environment(root)
    cli_main = root / "packages/yoke-cli/src/yoke_cli/main.py"
    cli_main.write_text(STUB_CLI_MAIN)
    return root.resolve()
