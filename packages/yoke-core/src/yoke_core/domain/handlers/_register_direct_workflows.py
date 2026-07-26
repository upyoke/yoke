"""Leaf registrations for Dash and Blitz execution operations."""

from yoke_core.domain.handlers.direct_workflow_execution import REGISTRATIONS


def register(registry) -> None:
    for entry in REGISTRATIONS:
        registry.register(**entry)


__all__ = ["register"]
