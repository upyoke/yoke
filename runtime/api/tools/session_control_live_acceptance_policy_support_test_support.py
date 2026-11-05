"""Synthetic exact-policy facts for live-qualification workflow tests."""

from yoke_contracts.session_control import private_route_versions
from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
)
from yoke_contracts.session_control.private_route_versions import (
    PRIVATE_ROUTE_VERSION_QUALIFICATIONS,
    PrivateRouteVersionQualification,
)


CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION = "1.34493.1"


def _require_exact_policy(monkeypatch, *, surface: str, operation: str) -> None:
    qualifications = dict(PRIVATE_ROUTE_VERSION_QUALIFICATIONS)
    qualifications[(surface, operation)] = PrivateRouteVersionQualification.exact(
        SESSION_SURFACE_CAPABILITIES[surface].minimum_version
    )
    monkeypatch.setattr(
        private_route_versions,
        "PRIVATE_ROUTE_VERSION_QUALIFICATIONS",
        qualifications,
    )


def require_exact_desktop_active_policy(monkeypatch) -> None:
    """Make the current desktop build unproven for generic grant tests."""
    _require_exact_policy(
        monkeypatch,
        surface="claude-desktop",
        operation="message_active",
    )


def require_exact_cli_idle_policy(monkeypatch) -> None:
    """Make a newer CLI build an explicit stage-qualification candidate."""
    _require_exact_policy(
        monkeypatch,
        surface="claude-cli",
        operation="message_idle",
    )


__all__ = [
    "CLAUDE_DESKTOP_EXACT_POLICY_CANDIDATE_VERSION",
    "require_exact_cli_idle_policy",
    "require_exact_desktop_active_policy",
]
