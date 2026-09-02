"""Wake-route expectations derived from a machine's installed surfaces."""

from __future__ import annotations

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
    parse_matrix,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    expected_wake_route,
    selected_route,
)
from runtime.api.tools.test_session_control_live_acceptance_contract import _matrix


def test_wake_route_derivation_covers_own_route_installed_peer_and_neither() -> None:
    assert expected_wake_route("codex-cli", "0.149.0", {}) == "direct"
    assert (
        expected_wake_route("claude-vscode", "2.1.238", {"claude-cli": "2.1.241"})
        == "direct"
    )
    assert (
        expected_wake_route("claude-vscode", "2.1.238", {"claude-vscode": "2.1.238"})
        == "none"
    )
    assert (
        expected_wake_route("claude-vscode", "2.1.238", {"claude-cli": "2.1.237"})
        == "none"
    )


def test_a_desktop_surface_has_no_route_even_with_a_qualified_peer() -> None:
    """The installed CLI is present and still names no route.

    That binary can technically resume the conversation, which is exactly
    the transcript fork the surface's operator wake authority refuses.
    """
    assert (
        expected_wake_route("claude-desktop", "1.34493.1", {"claude-cli": "2.1.241"})
        == "none"
    )


def test_matrix_wake_route_expectation_follows_the_installed_cli() -> None:
    raw = _matrix()
    for cell in raw["cells"]:
        if cell["surface"] == "claude-desktop":
            cell["wake_route"] = "direct"

    with pytest.raises(AcceptanceContractError) as raised:
        parse_matrix(raw)

    assert raised.value.code == "surface_wake_route_invalid"


def test_machine_relay_presence_selects_direct_or_the_one_hop_broker() -> None:
    assert selected_route(relay_fresh=True) == "direct"
    assert selected_route(relay_fresh=False) == "broker"
