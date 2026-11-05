# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import subprocess

from unittest.mock import Mock

import pytest

from runtime.api.domain.qa_case_ci_test_helpers import ci_case

from yoke_core.domain import qa_case_ci_run, qa_case_ci_lane, qa_case_ci_resume

from yoke_core.domain.qa_case_execution import (
    QaCaseExecutionError,
    execute_case_context,
)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, text=True, capture_output=True
    ).stdout.strip()
