"""Leaf registrations for Dash and Blitz execution operations."""

from yoke_core.domain.handlers.direct_workflow_conflict_survey_status import (
    REGISTRATIONS as CONFLICT_SURVEY_STATUS_REGISTRATIONS,
)
from yoke_core.domain.handlers.direct_workflow_execution import REGISTRATIONS


def register(registry) -> None:
    for entry in (*REGISTRATIONS, *CONFLICT_SURVEY_STATUS_REGISTRATIONS):
        registry.register(**entry)


__all__ = ["register"]
