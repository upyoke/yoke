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
SESSION_SURFACE_CAPABILITY_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-contracts/src/yoke_contracts/session_control/capabilities.py",
    }
)
SESSION_SURFACE_CAPABILITY_TESTS = (
    "runtime/api/domain/test_session_control_surface_versions.py",
    "runtime/api/domain/test_session_launch_requests.py",
    "runtime/api/domain/test_session_launch_surface_fallback.py",
    "runtime/api/domain/test_session_message_routing.py",
    "runtime/api/domain/test_session_message_wake_posture.py",
    "runtime/api/domain/test_session_message_wake_starvation.py",
    "runtime/api/domain/test_session_relay_wake_claim.py",
    "runtime/api/domain/test_session_relay_wake_posture.py",
)
_SESSION_CONTROL_CONTRACTS = (
    (
        "private_session_route_contract",
        PRIVATE_SESSION_ROUTE_SOURCE_PATHS,
        PRIVATE_SESSION_ROUTE_TESTS,
    ),
    (
        "session_surface_capability_contract",
        SESSION_SURFACE_CAPABILITY_SOURCE_PATHS,
        SESSION_SURFACE_CAPABILITY_TESTS,
    ),
)


def session_control_contract_selection(changed: Sequence[str]) -> ContractSelection:
    """Select operational consumers hidden by a broad package import graph."""
    changed_paths = tuple(dict.fromkeys(changed))
    tests: set[str] = set()
    widening_triggers: list[str] = []
    for rule, source_paths, contract_tests in _SESSION_CONTROL_CONTRACTS:
        hits = tuple(path for path in changed_paths if path in source_paths)
        if not hits:
            continue
        tests.update(contract_tests)
        widening_triggers.extend(f"{rule}:{path}" for path in hits)
    return ContractSelection(
        tests=frozenset(tests),
        widening_triggers=tuple(widening_triggers),
    )


__all__ = [
    "PRIVATE_SESSION_ROUTE_SOURCE_PATHS",
    "PRIVATE_SESSION_ROUTE_TESTS",
    "SESSION_SURFACE_CAPABILITY_SOURCE_PATHS",
    "SESSION_SURFACE_CAPABILITY_TESTS",
    "session_control_contract_selection",
]
