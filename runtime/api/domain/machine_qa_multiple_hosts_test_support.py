# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from runtime.api.domain.machine_qa_test_support import make_conn

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError as MachineCapabilityError,
    test_machine_capability_type as _machine_type,
)

from yoke_contracts.machine_qa_execution import (
    HOST_BASELINES,
    VERIFICATION_CHECKS,
)

from yoke_core.domain.coordination_claims import release

from yoke_core.domain.machine_qa_capability import (
    replace_test_machine_settings,
    test_machine_detail as read_test_machine_detail,
    test_machine_list as list_test_machines,
)

from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolLeaseHeld,
    begin_host_control_execution,
)

from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)

from yoke_core.domain.qa_test_machine_capability_context import (
    test_machine_capability_context as read_fleet_context,
)

from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)

MACHINES = ("mac-mini-lab", "mac-studio-lab")


def _settings(test_machine: str, *, notes: str = "") -> dict[str, str]:
    return {
        "resource_name": test_machine,
        "host": f"{test_machine}.local",
        "user": "yoke-test",
        "os": "macos",
        "operating_notes": notes,
    }


def _register_fleet(conn):
    first = replace_test_machine_settings(
        conn,
        project="yoke",
        settings=_settings(MACHINES[0]),
        base_settings=None,
    )
    second = replace_test_machine_settings(
        conn,
        project="yoke",
        test_machine=MACHINES[1],
        settings=_settings(MACHINES[1]),
        base_settings=None,
    )
    return first, second
