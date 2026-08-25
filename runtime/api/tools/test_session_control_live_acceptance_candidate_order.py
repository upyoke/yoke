"""Ordering and broker admission contract for stage-only acceptance proofs."""

from __future__ import annotations

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    ACCEPTANCE_SURFACES,
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


def _surface_cell(surface: str) -> dict:
    identify_only = surface == "claude-desktop"
    cell: dict = {
        "surface": surface,
        "expected_version": _version(surface),
        "mode": "identify" if identify_only else "create",
        "acceptance_role": "surface",
        "wake_route": "direct",
    }
    if identify_only:
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
        "wake_route": "broker",
        "broker_session_id": "broker-peer",
    }


def test_acceptance_matrix_runs_every_surface_before_any_broker() -> None:
    parsed = parse_readiness_matrix(
        {
            "schema": 2,
            "project": "yoke",
            "cells": [
                _broker_cell("codex-cli"),
                *(_surface_cell(surface) for surface in reversed(ACCEPTANCE_SURFACES)),
            ],
        }
    )

    assert tuple((cell.surface, cell.acceptance_role) for cell in parsed.cells) == (
        *((surface, "surface") for surface in ACCEPTANCE_SURFACES),
        ("codex-cli", "broker"),
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
                "schema": 2,
                "project": "yoke",
                "cells": [_broker_cell(surface)],
            }
        )

    assert raised.value.code == code
