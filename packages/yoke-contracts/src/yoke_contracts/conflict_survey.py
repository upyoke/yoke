"""Shared durable-state tokens for conflict-survey responses."""

from __future__ import annotations

from typing import Literal

DURABLE_ABSENT = "absent"
DURABLE_PENDING = "pending"
DURABLE_UNREADABLE = "unreadable"
DURABLE_RECORDED = "recorded"

ConflictSurveyRecordState = Literal[
    DURABLE_ABSENT,
    DURABLE_PENDING,
    DURABLE_UNREADABLE,
    DURABLE_RECORDED,
]
INCOMPLETE_DURABLE_STATES = frozenset({DURABLE_PENDING, DURABLE_UNREADABLE})

__all__ = [
    "ConflictSurveyRecordState",
    "DURABLE_ABSENT",
    "DURABLE_PENDING",
    "DURABLE_RECORDED",
    "DURABLE_UNREADABLE",
    "INCOMPLETE_DURABLE_STATES",
]
