"""Server-side reads and writes for the merge lock.

The merge lock is control-plane state, but the process that holds it is
local: liveness of a holder is decided from the client's own process table,
because that is where the merging process runs. These handlers therefore
carry only the row operations — list, insert, delete — and leave the
stale-holder decision to :mod:`yoke_core.domain.merge_lock` on the client.

Splitting it that way is what lets a merge take its lock over an https
control plane as well as against a local Postgres connection. Opening a
bare local connection for the lock, as the engine once did, fails outright
on an https-connected machine, which would leave concurrent merges
unserialized on exactly the transport most sessions use.

``adapter_status='internal'`` — merge glue, never an agent CLI surface, so
these carry no CLI adapter inventory row.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class LockListRequest(BaseModel):
    """Payload for ``merge.lock.list``."""

    now: str = Field(..., min_length=1)


class LockRow(BaseModel):
    id: int
    session_id: str
    branch: str
    epic_id: str = ""


class LockListResponse(BaseModel):
    rows: List[LockRow]


class LockAcquireRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    branch: str = Field(..., min_length=1)
    epic_id: Optional[str] = None
    acquired_at: str = Field(..., min_length=1)
    expires_at: str = Field(..., min_length=1)


class LockAcquireResponse(BaseModel):
    session_id: str
    branch: str


class LockReleaseRequest(BaseModel):
    """Release by holder identity, by explicit row ids, or every row."""

    session_id: Optional[str] = None
    branch: Optional[str] = None
    lock_ids: List[int] = Field(default_factory=list)
    all_rows: bool = False


class LockReleaseResponse(BaseModel):
    released: int


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _marker(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def handle_lock_list(request: FunctionCallRequest) -> HandlerOutcome:
    """Drop expired rows, then return whatever still holds the lock.

    The caller supplies ``now`` so expiry is judged against the merging
    machine's clock, the same one that set ``expires_at`` on acquire.
    """
    try:
        body = LockListRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"merge lock list payload invalid: {exc}")
    try:
        with _connect_rw() as conn:
            marker = _marker(conn)
            conn.execute(
                f"DELETE FROM merge_locks WHERE expires_at < {marker}",
                (body.now,),
            )
            conn.commit()
            rows = conn.execute(
                "SELECT id, session_id, branch, COALESCE(epic_id, '') "
                "FROM merge_locks"
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - lock state unavailable blocks merging
        return _err("merge_lock_read_failed", str(exc))
    return HandlerOutcome(
        result_payload=LockListResponse(
            rows=[
                LockRow(
                    id=int(row[0]),
                    session_id=str(row[1]),
                    branch=str(row[2]),
                    epic_id=str(row[3] or ""),
                )
                for row in rows
            ],
        ).model_dump(),
        primary_success=True,
    )


def handle_lock_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    """Insert one lock row for a holder the client has already identified."""
    try:
        body = LockAcquireRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"merge lock acquire payload invalid: {exc}")
    try:
        with _connect_rw() as conn:
            marker = _marker(conn)
            conn.execute(
                "INSERT INTO merge_locks "
                "(session_id, branch, epic_id, acquired_at, expires_at) "
                f"VALUES ({marker}, {marker}, {marker}, {marker}, {marker})",
                (
                    body.session_id,
                    body.branch,
                    body.epic_id or None,
                    body.acquired_at,
                    body.expires_at,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - a lock we cannot take is a hard stop
        return _err("merge_lock_acquire_failed", str(exc))
    return HandlerOutcome(
        result_payload=LockAcquireResponse(
            session_id=body.session_id, branch=body.branch,
        ).model_dump(),
        primary_success=True,
    )


def handle_lock_release(request: FunctionCallRequest) -> HandlerOutcome:
    """Delete lock rows: one holder's, a set the client found stale, or all."""
    try:
        body = LockReleaseRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - surface a structured payload error
        return _err("payload_invalid", f"merge lock release payload invalid: {exc}")
    try:
        with _connect_rw() as conn:
            marker = _marker(conn)
            if body.all_rows:
                cursor = conn.execute("DELETE FROM merge_locks")
            elif body.lock_ids:
                placeholders = ", ".join(marker for _ in body.lock_ids)
                cursor = conn.execute(
                    f"DELETE FROM merge_locks WHERE id IN ({placeholders})",
                    tuple(int(value) for value in body.lock_ids),
                )
            elif body.session_id and body.branch:
                cursor = conn.execute(
                    "DELETE FROM merge_locks "
                    f"WHERE session_id = {marker} AND branch = {marker}",
                    (body.session_id, body.branch),
                )
            else:
                return _err(
                    "payload_invalid",
                    "merge lock release needs all_rows, lock_ids, or "
                    "session_id + branch",
                )
            released = int(getattr(cursor, "rowcount", 0) or 0)
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - a stuck lock blocks every later merge
        return _err("merge_lock_release_failed", str(exc))
    return HandlerOutcome(
        result_payload=LockReleaseResponse(released=released).model_dump(),
        primary_success=True,
    )


__all__ = [
    "LockAcquireRequest",
    "LockAcquireResponse",
    "LockListRequest",
    "LockListResponse",
    "LockReleaseRequest",
    "LockReleaseResponse",
    "LockRow",
    "handle_lock_acquire",
    "handle_lock_list",
    "handle_lock_release",
]
