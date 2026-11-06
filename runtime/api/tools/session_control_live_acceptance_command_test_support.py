# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

from pathlib import Path

import stat

from types import SimpleNamespace

import pytest

from runtime.api.tools import session_control_live_acceptance_command as command

from runtime.api.tools.session_control_live_acceptance_contract import (
    ACCEPTANCE_SURFACE_CELLS,
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACES,
    AcceptanceContractError,
)

from runtime.api.tools.session_control_live_acceptance_policy_support_test_support import (
    CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION,
    require_exact_desktop_active_policy,
)

from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES

from yoke_core.domain.deploy_product_source import DeployProductSourceError

RELEASE_SHA = "a" * 40


def _versions() -> dict[str, str]:
    return {
        surface: SESSION_SURFACE_CAPABILITIES[surface].minimum_version
        for surface in ACCEPTANCE_SURFACES
    }


def _bindings() -> dict[str, object]:
    return {
        "schema": 1,
        "versions": _versions(),
        "claude_desktop_session_id": "desktop-session",
        "broker": {
            "target_session_id": "broker-target",
            "machine_id": "machine-one",
            "peer_session_id": "broker-peer",
        },
    }


def _argv(*extra: str) -> list[str]:
    return [
        "--project",
        "yoke",
        "--release-sha",
        RELEASE_SHA,
        "--run-id",
        "release-proof",
        "--bindings-stdin",
        *extra,
    ]


def _ready_decision():
    from runtime.api.tools.session_control_live_acceptance_broker_binding import (
        BrokerBinding,
        BrokerBindingDecision,
    )

    broker = _bindings()["broker"]
    return BrokerBindingDecision(
        "ready",
        BrokerBinding(
            broker["target_session_id"],
            broker["machine_id"],
            broker["peer_session_id"],
        ),
    )
