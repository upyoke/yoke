# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.product_wheel_environment import product_env as _product_env

import json

import os

import subprocess

from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    write_https_config,
)

from runtime.api.cli.product_pack_api import PackApi

from yoke_core.tools import package_index




def _assert_command(
    yoke: Path,
    cwd: Path,
    env: dict[str, str],
    args: list[str],
    expected_returncode: int | None,
    expected_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = _run(
        [str(yoke), *args],
        cwd=cwd,
        env=env,
        check=False,
    )
    if expected_returncode is not None:
        assert result.returncode == expected_returncode, _format_result(result)
    if expected_text is not None:
        assert expected_text in f"{result.stdout}\n{result.stderr}", _format_result(
            result
        )
    return result


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check:
        assert result.returncode == 0, _format_result(result)
    return result


def _format_result(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"command failed with {result.returncode}: {result.args!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
