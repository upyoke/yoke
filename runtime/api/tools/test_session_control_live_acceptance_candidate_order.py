"""Ordering and broker admission contract for stage-only acceptance proofs."""

from __future__ import annotations

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    ACCEPTANCE_SURFACE_CELLS,
    AcceptanceContractError,
    parse_candidate_matrix,
    parse_readiness_matrix,
)
from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES


CURRENT_CLAUDE_DESKTOP_VERSION = "1.34493.1"


def _version(surface: str) -> str:
    if surface == "claude-desktop":
        return CURRENT_CLAUDE_DESKTOP_VERSION
    return SESSION_SURFACE_CAPABILITIES[surface].minimum_version


def _surface_cell(surface: str, mode: str) -> dict:
    cell: dict = {
        "surface": surface,
        "expected_version": _version(surface),
        "mode": mode,
        "acceptance_role": "surface",
        "proof_scope": "registered_session_control_surface",
        "wake_route": "direct",
    }
    if mode == "identify":
        cell["session_id"] = "claude-desktop-session"
    return cell


def _broker_cell(surface: str) -> dict:
    return {
        "surface": surface,
        "expected_version": _version(surface),
        "mode": "identify",
        "session_id": "broker-target",
        "machine_id": "machine-1",
        "acceptance_role": "broker",
        "proof_scope": "registered_broker_wake_route",
        "wake_route": "machine_selected",
        "broker_session_id": "broker-peer",
    }


def test_acceptance_matrix_runs_every_surface_before_any_broker() -> None:
    parsed = parse_readiness_matrix(
        {
            "schema": SCHEMA_VERSION,
            "project": "yoke",
            "cells": [
                _broker_cell("codex-cli"),
                *(
                    _surface_cell(surface, mode)
                    for surface, mode in reversed(ACCEPTANCE_SURFACE_CELLS)
                ),
            ],
        }
    )

    assert tuple((cell.surface, cell.mode) for cell in parsed.cells) == (
        *ACCEPTANCE_SURFACE_CELLS,
        ("codex-cli", "identify"),
    )


@pytest.mark.parametrize(
    ("surface", "code"),
    (
        ("claude-desktop", "broker_surface_unproven"),
        ("claude-cli", "candidate_route_not_private"),
    ),
)
def test_candidate_matrix_refuses_broker_proofs_with_a_named_reason(
    surface: str, code: str
) -> None:
    with pytest.raises(AcceptanceContractError) as raised:
        parse_candidate_matrix(
            {
                "schema": SCHEMA_VERSION,
                "project": "yoke",
                "cells": [_broker_cell(surface)],
            }
        )

    assert raised.value.code == code
