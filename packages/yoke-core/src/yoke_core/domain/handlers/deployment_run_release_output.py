"""Registered write for the commits a release's own automation produced.

A promotion that rewrites a version pin pushes a real commit no backlog item
authored. This is where the run that pushed it says so, once, so that every
later release reads an attributed commit instead of refusing an unexplained
one. The refusals are the point of the surface: an unresolvable commit and a
commit a backlog item already owns are both named rather than recorded,
because a record that could absorb either would be a waiver wearing an
attribution's clothes.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.deployment_run_release_output import REASON_RELEASE_PIN
from yoke_core.domain.deployment_run_release_output_record import (
    ReleaseOutputRefused,
    record_release_output,
)
from yoke_core.domain.handlers.deployment_common import error, run_id


class DeploymentRunReleaseOutputRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[str] = None
    project: str = Field(min_length=1)
    commit_sha: str = Field(default="", max_length=64)
    reason: str = Field(default=REASON_RELEASE_PIN, min_length=1, max_length=120)


class DeploymentRunReleaseOutputRecordResponse(BaseModel):
    run_id: str
    project: str
    project_id: int
    commit_sha: str
    reason: str
    recorded: bool
    outcome: str


def handle_deployment_run_release_output_record(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Record one commit as the named run's own release output."""
    function_id = "deployment_runs.release_output.record"
    resolved_run_id = run_id(request, function_id)
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    project = str(payload.get("project") or "").strip()
    commit_sha = str(payload.get("commit_sha") or "").strip()
    reason = str(payload.get("reason") or REASON_RELEASE_PIN).strip()
    if not project:
        return error(
            "payload_invalid",
            f"{function_id} requires the project whose source holds the commit",
            jsonpath="$.payload.project",
        )

    from yoke_core.domain.db_helpers import connect

    conn = connect(None)
    try:
        receipt = record_release_output(
            conn,
            run_id=resolved_run_id,
            project=project,
            commit_sha=commit_sha,
            reason=reason or REASON_RELEASE_PIN,
        )
        conn.commit()
    except ReleaseOutputRefused as exc:
        conn.rollback()
        return error(exc.reason, str(exc), jsonpath="$.payload.commit_sha")
    except LookupError as exc:
        conn.rollback()
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
    except ValueError as exc:
        conn.rollback()
        return error("validation_error", str(exc), jsonpath="$.payload.project")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=receipt)


__all__ = [
    "DeploymentRunReleaseOutputRecordRequest",
    "DeploymentRunReleaseOutputRecordResponse",
    "handle_deployment_run_release_output_record",
]
