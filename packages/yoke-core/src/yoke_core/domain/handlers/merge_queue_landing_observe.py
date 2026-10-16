"""Registered server observation of one item's project landing records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_attempt import read_latest_attempt
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.domain.merge_queue_landing_refresh import (
    LANDING_RECORD_STALE_SECONDS,
    LandingRefresh,
    read_refresh,
    record_age_seconds,
)
from yoke_core.domain.session_message_types import row_dict, utc_now
from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_contracts.public_ref import ITEM_NOT_FOUND


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


def _lane_pull_requests(conn: Any, item_id: int, item_pr_number: str) -> set[str]:
    """The pull requests whose stored observation answers this lane.

    An open re-land attempt is the landing in flight. Without one, the
    item's current landing answers, and so does the attempt that just
    closed: its last observation is how a waiter learns it closed unmerged
    instead of waiting on a pull request nobody will merge.
    """
    attempt = read_latest_attempt(conn, item_id)
    if attempt is not None and attempt["closed_at"] is None:
        return {attempt["pr_number"]}
    lane = {item_pr_number}
    if attempt is not None:
        lane.add(attempt["pr_number"])
    return lane


def _stored_record(conn: Any, item_id: int, pr_numbers: set[str]) -> Any:
    """This lane's durable record, or None when it describes another PR."""
    record = read_landing_record(conn, item_id)
    if record is not None and record.pr_number not in pr_numbers:
        return None
    return record


def _stale(record: Any, refresh: LandingRefresh, *, now: datetime) -> bool:
    """Whether the stored answer is too old or too doubtful to return as is.

    A sweep still running inside the stale window is about to write a fresh
    answer. Otherwise the record ages from its own observation; before the
    first record exists, the project's last sweep is the newest evidence.
    A sweep that ended in error leaves every stored answer doubtful.
    """
    refresh_age = record_age_seconds(refresh.started_at, now=now)
    if refresh.in_progress and (
        refresh_age is not None and refresh_age <= LANDING_RECORD_STALE_SECONDS
    ):
        return False
    if record is not None:
        age = record_age_seconds(record.observed_at, now=now)
        stale = age is None or age > LANDING_RECORD_STALE_SECONDS
    else:
        stale = refresh_age is None or refresh_age > LANDING_RECORD_STALE_SECONDS
    return stale or bool(refresh.last_error)


def handle_observe_landing(request: FunctionCallRequest) -> HandlerOutcome:
    """Return this lane's durable record, reading GitHub only when it is stale.

    Relay upkeep keeps records current on the shared project cadence, so a
    fresh record answers without any GitHub read. When no relay sweep has
    kept it current (no relay running, or a single-machine install), this
    call refreshes the project inline, so a waiter never waits on a record
    nobody refreshes.
    """
    if request.target.item_id is None:
        return _error("target_invalid", "landing.observe requires target.public_ref")
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
                return _error("target_not_found", ITEM_NOT_FOUND)
            item = row_dict(row)
            project_id = int(item["project_id"])
            pr_numbers = _lane_pull_requests(
                conn, item_id, str(item.get("merge_queue_pr_number") or "")
            )
            before = read_refresh(conn, project_id)
            after = before
            record = _stored_record(conn, item_id, pr_numbers)
            observation_error = ""
            if _stale(record, before, now=current):
                try:
                    observe_pending_landings(conn, [project_id], now=current)
                except Exception as exc:  # The refresh row carries this evidence.
                    observation_error = str(exc)
                after = read_refresh(conn, project_id)
                record = _stored_record(conn, item_id, pr_numbers)
            stale = _stale(record, after, now=current) or bool(observation_error)
            age = record_age_seconds(
                record.observed_at if record is not None else None,
                now=current,
            )
    except Exception as exc:  # noqa: BLE001 - named server-side refusal
        return _error(
            "landing_observation_failed",
            f"server landing observation failed for {item_ref_for_id(item_id)}: {exc}",
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
