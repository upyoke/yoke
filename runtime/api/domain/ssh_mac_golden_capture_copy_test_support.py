# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import base64

import ctypes

import os

from pathlib import Path

import shlex

import subprocess

import sys

import pytest

from runtime.api.domain.ssh_mac_golden_capture_test_support import (
    FakeCaptureTransport,
    _capture,
)

from yoke_cli.config.path_doctor import resolve_path_state_contract

from yoke_contracts.ssh_mac_full_reset_contract import resolve_full_reset_path_contract

from yoke_harness.ssh_mac_golden_capture_contract import (
    CAPTURE_COPY_STDERR_LIMIT,
    CAPTURE_COPY_STDERR_PREFIX,
    CAPTURE_FAILURE_PREFIX,
    CAPTURE_PHASES,
)

from yoke_harness.ssh_mac_golden_capture_receipt import (
    capture_failure_outcome,
    closed_capture_outcomes,
)

from yoke_harness.ssh_mac_golden_capture_script import render_golden_capture_script


def _run_capture(home: Path, destination: Path, tmp_path: Path):
    script = render_golden_capture_script(
        resolve_full_reset_path_contract(
            resolve_path_state_contract(target="posix",
                env={"HOME": "/Users/tester", "SHELL": "/bin/zsh"}
