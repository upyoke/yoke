"""Typed aggregate and on-demand contributor reads for Performance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.actor_permissions import PermissionDenied
from yoke_core.domain.db_helpers import connect
from yoke_core.domain import db_backend
from yoke_core.domain.performance_metrics import MAX_POINTS, aggregate
from yoke_core.domain.performance_query import (
    MAX_OBSERVATIONS,
    details,
    read_observations,
)


class PerformanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    since: datetime
    until: datetime
    project_ids: list[int] | None = Field(default=None, max_length=100)
    points: int = Field(default=400, ge=20, le=MAX_POINTS)


class PerformanceDetailRequest(PerformanceRequest):
    family: Literal["function", "tool", "hook", "relay", "watcher"] | None = None
    offset: int = Field(default=0, ge=0, le=MAX_OBSERVATIONS)
    limit: int = Field(default=50, ge=1, le=100)


class PerformanceResponse(BaseModel):
    buckets: list[dict[str, Any]]
    bucket_seconds: int
    observation_count: int
    last_observation: str | None
    queried_at: str
    coverage: str


class PerformanceDetailResponse(BaseModel):
    rows: list[dict[str, Any]]
    total: int
    offset: int
    next_offset: int | None
    sampling: str
    span_coverage: str


def _read(request: FunctionCallRequest, detail: bool) -> HandlerOutcome:
    model = PerformanceDetailRequest if detail else PerformanceRequest
    value = model.model_validate(request.payload)
    start, end = value.since, value.until
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="performance_range_invalid",
                message="Use timezone-qualified From/To timestamps with From before To.",
            ),
        )
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    try:
        with connect() as conn:
            observations = read_observations(
                conn, request.actor.actor_id, value.project_ids, start, end
            )
        if detail:
            result = details(observations, value.family, value.offset, value.limit)
        else:
            result = aggregate(
                observations, start.timestamp(), end.timestamp(), value.points
            )
            result.update(
                queried_at=datetime.now(timezone.utc).isoformat(),
                coverage=(
                    "Delivered retained observations only; gaps and older history are unknown. "
                    "Last observation is not proof of collector health. Unattributed observations "
                    "appear only in All for authorized universe admins; never in project metrics. "
                    "Hook series measures evaluator time; client wall is available in inspection."
                ),
            )
        return HandlerOutcome(primary_success=True, result_payload=result)
    except (PermissionDenied, ValueError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="performance_scope_denied"
                if isinstance(exc, PermissionDenied)
                else "performance_query_refused",
                message=str(exc),
            ),
        )
    except db_backend.database_error_types():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="performance_query_unavailable",
                message="Timing event storage could not answer this range. Retry Refresh; if it persists, ask the universe operator to check event storage and schema convergence.",
            ),
        )


def handle_aggregate(request: FunctionCallRequest) -> HandlerOutcome:
    return _read(request, False)


def handle_detail(request: FunctionCallRequest) -> HandlerOutcome:
    return _read(request, True)
