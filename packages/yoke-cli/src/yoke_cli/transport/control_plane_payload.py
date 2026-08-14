"""Fail-closed reads from payloads returned by a control plane.

Payload contracts can move before every connected server deploys the same
build.  The HTTPS handshake records the server build and, for source
checkouts, the existing git comparison.  Readers use :func:`required_field`
instead of a raw mapping subscript when a missing field can mean version
skew.  A mismatch then names the deployed build and an actionable recovery
instead of leaking an unexplained ``KeyError``.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_cli.transport import source_build_skew


class ControlPlanePayloadError(RuntimeError):
    """A connected control plane did not satisfy a required payload contract."""


@dataclass(frozen=True)
class ObservedServerBuild:
    """Build identity carried by the latest HTTPS response in this context."""

    name: str = ""
    comparison: Optional[source_build_skew.BuildComparison] = None


_OBSERVED_SERVER_BUILD: ContextVar[ObservedServerBuild] = ContextVar(
    "observed_control_plane_server_build",
    default=ObservedServerBuild(),
)


def observe_server_build(
    name: str,
    comparison: Optional[source_build_skew.BuildComparison] = None,
) -> None:
    """Bind one response's server build to subsequent payload reads."""
    current = _OBSERVED_SERVER_BUILD.get()
    if name and name == current.name and comparison is None:
        comparison = current.comparison
    _OBSERVED_SERVER_BUILD.set(ObservedServerBuild(name=name, comparison=comparison))


def required_field(payload: Mapping[str, Any], field: str) -> Any:
    """Return a required field or refuse with control-plane skew recovery."""
    if field in payload:
        return payload[field]
    observed = _OBSERVED_SERVER_BUILD.get()
    build = observed.name or "unknown"
    comparison = observed.comparison
    if comparison is not None and comparison.relationship == source_build_skew.AHEAD:
        mismatch = (
            f"control-plane server build {build} predates this client checkout; "
            f"{source_build_skew.describe(comparison)}"
        )
    else:
        mismatch = f"control-plane server build {build} does not match this client"
    recovery = (
        f"pin the client checkout to {build}"
        if observed.name
        else "use a client build matching the deployed server"
    )
    raise ControlPlanePayloadError(
        f"{mismatch}. It did not provide required payload field {field!r}. "
        "Deploy a server release carrying this payload contract, or "
        f"{recovery}."
    )


__all__ = [
    "ControlPlanePayloadError",
    "observe_server_build",
    "required_field",
]
