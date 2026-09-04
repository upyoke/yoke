"""Record that the calling session is waiting on one CI run's verdict.

The write is deliberately session-scoped and claim-free: a gate dispatches
CI from wherever the work is happening, and the only fact being asserted is
"this session dispatched this run". The project comes from the session row
rather than the payload, so a caller cannot register a wait against a
project it is not working in.

Re-recording the same run for the same session is a no-op. A rejoined run
is the same run, and a session that has already been told its verdict must
not be told again by a second row.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.session_ci_wait_schema import CI_WAIT_KINDS
from yoke_core.domain.session_message_types import timestamp, utc_now


class RecordCiWaitRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    run_id: str = Field(..., min_length=1, description="GitHub Actions run id.")
    kind: str = Field(..., description="Which gate dispatched the run.")
    head_sha: str = Field("", description="The commit the run checked out.")
    continue_command: str = Field(
        "",
        description="The exact command that resumes this wait once the "
        "verdict lands.",
    )
    supersedes_run_id: str = Field(
        "",
        description="A run this one replaces; its pending wait is dropped.",
    )


class RecordCiWaitResponse(BaseModel):
    session_id: str
    project_id: int
    run_id: str
    recorded: bool


def _err(code: str, message: str) -> HandlerOutcome:
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


def handle_record_ci_wait(request: FunctionCallRequest) -> HandlerOutcome:
    """Persist one pending CI wait for the calling session."""
    session_id = request.actor.session_id or ""
    if not session_id:
        return _err(
            "session_required",
            "session_ci_wait.record names the session owed the verdict, so it "
            "requires an ambient harness session",
        )
    try:
        body = RecordCiWaitRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _err("payload_invalid", f"ci wait payload invalid: {exc}")
    if body.kind not in CI_WAIT_KINDS:
        return _err(
            "payload_invalid",
            f"kind must be one of {', '.join(CI_WAIT_KINDS)}, got {body.kind!r}",
        )

    now = timestamp(utc_now())
    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                f"SELECT project_id FROM harness_sessions WHERE session_id={p}",
                (session_id,),
            ).fetchone()
            if row is None or row[0] is None:
                return _err(
                    "session_not_found",
                    f"session {session_id} has no registered project to sweep "
                    "for; re-register the session and retry",
                )
            project_id = int(row[0])
            recorded = _insert(
                conn,
                p,
                session_id=session_id,
                project_id=project_id,
                body=body,
                now=now,
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - advisory gate-side warning
        return _err("ci_wait_record_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "session_id": session_id,
            "project_id": project_id,
            "run_id": body.run_id,
            "recorded": recorded,
        },
        primary_success=True,
    )


def _insert(
    conn: Any,
    p: str,
    *,
    session_id: str,
    project_id: int,
    body: RecordCiWaitRequest,
    now: str,
) -> bool:
    """Insert the wait unless this session already recorded this run."""
    if body.supersedes_run_id:
        conn.execute(
            f"DELETE FROM session_ci_run_waits WHERE session_id={p} "
            f"AND run_id={p} AND notified_at IS NULL",
            (session_id, body.supersedes_run_id),
        )
    existing: Optional[Any] = conn.execute(
        f"SELECT id FROM session_ci_run_waits WHERE session_id={p} AND run_id={p}",
        (session_id, body.run_id),
    ).fetchone()
    if existing is not None:
        return False
    conn.execute(
        "INSERT INTO session_ci_run_waits "
        "(session_id,project_id,repo,run_id,head_sha,kind,continue_command,"
        f"created_at) VALUES ({p},{p},{p},{p},{p},{p},{p},{p})",
        (
            session_id,
            project_id,
            body.repo,
            body.run_id,
            body.head_sha,
            body.kind,
            body.continue_command,
            now,
        ),
    )
    return True


__all__ = [
    "RecordCiWaitRequest",
    "RecordCiWaitResponse",
    "handle_record_ci_wait",
]
