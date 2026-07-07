"""Shared helpers for test_epic_task_sync*.py modules.

Pure helpers (no pytest fixtures) — safe to import from any test module
without triggering pytest fixture-discovery side effects. The naming
convention `<stem>_test_helpers.py` keeps pytest from collecting an
empty test module.
"""

from __future__ import annotations

import subprocess


def cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a subprocess.CompletedProcess for command-call mocks."""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)
