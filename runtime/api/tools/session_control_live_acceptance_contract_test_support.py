# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from types import SimpleNamespace

import pytest

from runtime.api.tools import session_control_live_acceptance_client as client_module

from runtime.api.tools.session_control_live_acceptance_client import YokeCliClient

from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACE_CELLS,
    AcceptanceContractError,
    parse_candidate_matrix,
    parse_matrix,
    parse_readiness_matrix,
    validate_deployed_release,
    validate_run_id,
)

from runtime.api.tools.session_control_live_acceptance_policy_support_test_support import (
    CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION,
    require_exact_desktop_active_policy,
)

VERSIONS = {
    "claude-cli": "2.1.238",
    "claude-desktop": "1.32885.1",
    "codex-cli": "0.149.0-alpha.4.3",
    "cursor-cli": "2026.08.11-e8db854",
}


def _matrix() -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "project": "yoke",
        "cells": [
            {
                "surface": surface,
                "expected_version": VERSIONS[surface],
                "mode": mode,
                "acceptance_role": "surface",
                "proof_scope": "registered_session_control_surface",
                # A desktop surface is its operator's to wake, never ours.
                "wake_route": "none" if surface == "claude-desktop" else "direct",
                **(
                    {"session_id": "claude-desktop-session"}
                    if mode == "identify"
                    else {}
                ),
            }
            for surface, mode in reversed(ACCEPTANCE_SURFACE_CELLS)
        ]
        + [
            {
                "surface": "codex-cli",
                "expected_version": VERSIONS["codex-cli"],
                "mode": "identify",
                "session_id": "broker-target-session",
                "machine_id": "machine-1",
                "acceptance_role": "broker",
                "proof_scope": "registered_broker_wake_route",
                "wake_route": "machine_selected",
                "broker_session_id": "broker-peer-session",
            }
        ],
    }
