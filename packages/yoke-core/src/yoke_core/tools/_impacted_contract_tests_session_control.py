"""Bounded impact companions for private session-route policy."""

from __future__ import annotations

from collections.abc import Sequence

from yoke_core.tools._impacted_contract_tests import ContractSelection


PRIVATE_SESSION_ROUTE_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-contracts/src/yoke_contracts/session_control/"
        "private_route_versions.py",
        "packages/yoke-contracts/src/yoke_contracts/session_control/"
        "surface_versions.py",
    }
)
PRIVATE_SESSION_ROUTE_TESTS = (
    "runtime/api/domain/test_session_message_qualification_ack.py",
    "runtime/api/domain/test_session_message_routing.py",
)


def session_control_contract_selection(changed: Sequence[str]) -> ContractSelection:
    """Select operational consumers hidden by a broad package import graph."""
    hits = tuple(
        path
        for path in dict.fromkeys(changed)
        if path in PRIVATE_SESSION_ROUTE_SOURCE_PATHS
    )
    return ContractSelection(
        tests=frozenset(PRIVATE_SESSION_ROUTE_TESTS) if hits else frozenset(),
        widening_triggers=tuple(
            f"private_session_route_contract:{path}" for path in hits
        ),
    )


__all__ = [
    "PRIVATE_SESSION_ROUTE_SOURCE_PATHS",
    "PRIVATE_SESSION_ROUTE_TESTS",
    "session_control_contract_selection",
]
