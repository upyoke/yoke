# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

import shlex

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    FakeResetTransport,
    GOLDEN_BASELINE_PATH,
    closed_reset_stdout,
)

from yoke_cli.config import path_doctor

from yoke_harness.ssh_mac_full_reset import execute_full_test_machine_reset

from yoke_contracts.ssh_mac_full_reset_contract import (
    FULL_DISK_ACCESS_PROBE_PATH,
    FULL_RESET_REMOTE_PATH,
    RESET_FAILURE_PREFIX,
    RESET_PHASES,
)

from yoke_harness.ssh_mac_full_reset_script import FULL_RESET_SCRIPT

from yoke_harness.ssh_mac_full_reset import is_safe_test_mac_home

from yoke_contracts.ssh_mac_full_reset_contract import (
    INSTALLER_TEMP_PATH,
    RESET_ABSENT_KIND_LEFTOVER,
    RESET_ABSENT_PATH_PREFIX,
    RESET_ABSENT_RECOVERY,
    RESET_RESTORE_ERROR_PREFIX,
    RESET_RESTORE_UNRESTORED_PREFIX,
    SELF_HOST_COMPOSE_PROJECT,
)

from yoke_contracts.ssh_mac_preserved_state import PRESERVED_HOME_ENTRIES

HOME = "/Users/tester"


def _run(transport: FakeResetTransport, **overrides):
    arguments = {
        "run_remote": transport.run,
        "upload_text": transport.upload,
        "home": HOME,
        "golden_baseline_path": GOLDEN_BASELINE_PATH,
    }
    arguments.update(overrides)
    return execute_full_test_machine_reset(**arguments)
