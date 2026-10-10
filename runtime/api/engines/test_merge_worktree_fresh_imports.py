"""Merge cleanup imports must work without a preloaded parent engine."""

from __future__ import annotations

import subprocess
import sys

import pytest


CLEANUP_MODULE = "yoke_core.engines.merge_worktree_cleanup"
HELPERS_MODULE = "yoke_core.engines.merge_worktree_post_helpers"


@pytest.mark.parametrize(
    "modules",
    [
        (CLEANUP_MODULE,),
        (HELPERS_MODULE,),
        (CLEANUP_MODULE, HELPERS_MODULE),
        (HELPERS_MODULE, CLEANUP_MODULE),
    ],
)
def test_cleanup_modules_import_in_fresh_interpreter(modules):
    code = (
        "import importlib, sys\n"
        "assert not any(name.startswith('yoke_core') for name in sys.modules)\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
