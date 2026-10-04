"""Registered retirement writes; historical project reads remain available."""

from __future__ import annotations

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_retirement import ProjectRetirementError, set_retirement


class RetireRequest(BaseModel):
    project: str
    reason: str = Field(min_length=1)


class UnretireRequest(BaseModel):
    project: str


class RetirementResponse(BaseModel):
    project_id: int
    project: str
    retired_at: str | None
    changed: bool


def _handle(request, *, retired: bool):
    parsed = (RetireRequest if retired else UnretireRequest)(**request.payload)
    conn = connect()
    try:
        result = set_retirement(
            conn,
            str((request.options or {}).get("authorized_project_id") or parsed.project),
            retired=retired,
            reason=parsed.reason if retired else "Project restored to active inventory",
            session_id=request.actor.session_id if request.actor else "",
        )
        conn.commit()
        return HandlerOutcome(primary_success=True, result_payload=result)
    except ProjectRetirementError as exc:
        conn.rollback()
        return HandlerOutcome(
            primary_success=False, error=FunctionError(code=exc.code, message=str(exc))
        )
    except LookupError as exc:
        conn.rollback()
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="project_not_found",
                message=f"{exc}; list projects with --include-retired and retry.",
            ),
        )
    finally:
        conn.close()


def handle_retire(request):
    return _handle(request, retired=True)


def handle_unretire(request):
    return _handle(request, retired=False)
