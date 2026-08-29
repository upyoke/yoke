"""Claude desktop create stays a designed deferral in the acceptance matrix."""

from __future__ import annotations

import pytest

from runtime.api.tools.session_control_live_acceptance_cells import (
    ACCEPTANCE_SURFACE_CELLS,
    acceptance_operation,
)
from runtime.api.tools.session_control_live_acceptance_contract import (
    SCHEMA_VERSION,
    AcceptanceContractError,
    parse_candidate_matrix,
)
from yoke_contracts.session_control.surface_versions import (
    surface_operation_supported,
)


def test_claude_desktop_create_is_not_an_acceptance_cell() -> None:
    assert ("claude-desktop", "create") not in ACCEPTANCE_SURFACE_CELLS
    assert ("claude-desktop", "identify") in ACCEPTANCE_SURFACE_CELLS
    assert acceptance_operation("claude-desktop", "create") == "create"
    assert not surface_operation_supported("claude-desktop", "1.32885.1", "create")


def test_matrix_refuses_a_claude_desktop_create_cell() -> None:
    raw = {
        "schema": SCHEMA_VERSION,
        "project": "yoke",
        "cells": [
            {
                "surface": "claude-desktop",
                "expected_version": "1.32885.1",
                "mode": "create",
                "acceptance_role": "surface",
                "proof_scope": "registered_session_control_surface",
                "wake_route": "direct",
            }
        ],
    }

    with pytest.raises(AcceptanceContractError) as raised:
        parse_candidate_matrix(raw)

    assert raised.value.code == "create_unproven"
