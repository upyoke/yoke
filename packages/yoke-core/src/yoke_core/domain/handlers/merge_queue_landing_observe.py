"""Registered server observation of one item's project landing records."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.domain.merge_queue_landing_refresh import (
    LANDING_RECORD_STALE_SECONDS,
    read_refresh,
    record_age_seconds,
)
from yoke_core.domain.session_message_types import utc_now


class ObserveLandingRequest(BaseModel):
    pass


class ObserveLandingResponse(BaseModel):
    item_id: int
    project_id: int
    refreshed: bool
    stale: bool
    age_seconds: float | None
    stale_after_seconds: float
    record: dict[str, Any] | None
    refresh: dict[str, Any]


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def handle_observe_landing(request: FunctionCallRequest) -> HandlerOutcome:
    """Refresh one project if due, then return this lane's durable record."""
    if request.target.item_id is None:
        return _error("target_invalid", "landing.observe requires target.item_id")
    try:
        ObserveLandingRequest.model_validate(request.payload)
    except Exception as exc:  # Pydantic supplies the actionable field path.
        return _error("payload_invalid", f"landing observation payload invalid: {exc}")

    item_id = int(request.target.item_id)
    current = utc_now()
    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                f"SELECT project_id,merge_queue_pr_number FROM items WHERE id={p}",
                (item_id,),
            ).fetchone()
            if row is None:
                return _error("target_not_found", f"item {item_id} not found")
            project_id = int(row[0])
            pr_number = str(row[1] or "")
            before = read_refresh(conn, project_id)
            observation_error = ""
            try:
                observe_pending_landings(conn, [project_id], now=current)
            except Exception as exc:  # The refresh row carries this evidence.
                observation_error = str(exc)
            after = read_refresh(conn, project_id)
            record = read_landing_record(conn, item_id)
            if record is not None and record.pr_number != pr_number:
                record = None
            age = record_age_seconds(
                record.observed_at if record is not None else "",
                now=current,
            )
            refresh_age = record_age_seconds(after.started_at, now=current)
            if after.in_progress and (
                refresh_age is not None and refresh_age <= LANDING_RECORD_STALE_SECONDS
            ):
                stale = False
            elif record is not None:
                stale = age is None or age > LANDING_RECORD_STALE_SECONDS
            else:
                stale = (
                    refresh_age is None or refresh_age > LANDING_RECORD_STALE_SECONDS
                )
            stale = stale or bool(observation_error or after.last_error)
    except Exception as exc:  # noqa: BLE001 - named server-side refusal
        return _error(
            "landing_observation_failed",
            f"server landing observation failed for item {item_id}: {exc}",
        )

    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "project_id": project_id,
            "refreshed": after.started_at != before.started_at,
            "stale": stale,
            "age_seconds": age,
            "stale_after_seconds": LANDING_RECORD_STALE_SECONDS,
            "record": record.payload() if record is not None else None,
            "refresh": after.payload(),
        },
        primary_success=True,
    )


__all__ = [
    "ObserveLandingRequest",
    "ObserveLandingResponse",
    "handle_observe_landing",
]
