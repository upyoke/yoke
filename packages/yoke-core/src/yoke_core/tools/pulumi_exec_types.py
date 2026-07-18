"""Shared types for the bounded Pulumi execution modules."""

from __future__ import annotations


AMBIENT_GITHUB_ENV = frozenset({
    "GH_ENTERPRISE_TOKEN",
    "GH_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GITHUB_TOKEN",
    "RUNNER_FLEET_GITHUB_TOKEN",
})


class PulumiExecError(RuntimeError):
    """The requested local Pulumi operation is outside the safe boundary."""


__all__ = ["AMBIENT_GITHUB_ENV", "PulumiExecError"]
