# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
)

from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
)

from runtime.api.tools.session_control_live_acceptance_driver_test_support import (
    RELEASE_SHA,
    SERVER_BUILD,
    _ScenarioClient,
    _driver,
)


def _broker_cell() -> AcceptanceCell:
    return AcceptanceCell(
        "codex-cli",
        "0.148.0-alpha.15",
        "identify",
        session_id="broker-target-session",
        machine_id="machine-1",
        acceptance_role="broker",
        wake_route=MACHINE_SELECTED_ROUTE,
        broker_session_id="broker-peer-session",
    )
