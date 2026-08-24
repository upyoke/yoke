"""Wake-route expectations derived from a machine's installed surfaces."""

from __future__ import annotations

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
    parse_matrix,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    expected_wake_route,
)
from runtime.api.tools.test_session_control_live_acceptance_contract import _matrix


def test_wake_route_derivation_covers_own_route_installed_peer_and_neither() -> None:
    assert expected_wake_route("codex-cli", "0.149.0", {}) == "direct"
    assert (
        expected_wake_route("claude-desktop", "1.34493.1", {"claude-cli": "2.1.241"})
        == "direct"
    )
    assert (
        expected_wake_route(
            "claude-desktop", "1.34493.1", {"claude-desktop": "1.34493.1"}
        )
        == "none"
    )
    assert (
        expected_wake_route("claude-desktop", "1.34493.1", {"claude-cli": "2.1.237"})
        == "none"
    )


def test_matrix_wake_route_expectation_follows_the_installed_cli() -> None:
    raw = _matrix()
    for cell in raw["cells"]:
        if cell["surface"] == "claude-desktop":
            cell["wake_route"] = "none"

    with pytest.raises(AcceptanceContractError) as raised:
        parse_matrix(raw)

    assert raised.value.code == "surface_wake_route_invalid"
