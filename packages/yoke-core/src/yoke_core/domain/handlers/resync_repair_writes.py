"""Internal server-side write for the resync repair path.

After creating a GitHub issue for a local-orphan epic task, the resync
repair helper wrote the new issue number back into the task's
``github_issue`` field by opening a local ``connect()``, which fails over
an https control plane (no local Postgres). This handler relays that
write server-side (dispatched in-process against a local Postgres
connection, or over https server-side) while the helper keeps the
``github_rest.create_issue`` call local — the read → GitHub create →
write-back ordering is preserved because the GitHub create between the
relayed reads and this relayed write touches no Yoke DB.

The handler is a thin wrapper over the unchanged
:func:`yoke_core.domain.epic_task_crud.task_update_field` write. It is
``adapter_status='internal'`` (repair glue, never an agent CLI surface),
so it needs no CLI adapter row, and ``ambient_session_required=False``
because a resync run may resolve no ambient harness session. It is
``claim_required_kind=None`` because the inline write it replaces opened a
raw control-plane connection with no claim check; the ``PROJECT`` +
``PERM_ITEMS_WRITE`` authorization scope
(``function_authz_product_scopes``) gates the write instead.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class EpicTaskGithubIssueSetRequest(BaseModel):
    epic_ref: str = Field(..., min_length=1)
    task_num: int
    issue_ref: str = Field(..., min_length=1)


class EpicTaskGithubIssueSetResponse(BaseModel):
    updated: bool


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_epic_task_github_issue_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Write the new GitHub issue reference into ``epic_tasks.github_issue``.

    Wraps the unchanged
    :func:`yoke_core.domain.epic_task_crud.task_update_field` write (which
    commits and best-effort touches activity). Any failure surfaces as a
    structured error so the caller degrades exactly as its inline
    ``except Exception: pass`` did — the issue exists; the field write is
    advisory.
    """
    try:
        body = EpicTaskGithubIssueSetRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"epic_task_github_issue_set invalid: {exc}")

    from yoke_core.domain.epic_task_crud import task_update_field

    try:
        with _connect_rw() as conn:
            task_update_field(
                conn,
                str(body.epic_ref),
                int(body.task_num),
                "github_issue",
                body.issue_ref,
            )
    except Exception as exc:  # noqa: BLE001 - surfaced so the caller degrades
        return _err("epic_task_github_issue_set_failed", str(exc))

    return HandlerOutcome(
        result_payload={"updated": True}, primary_success=True
    )


__all__ = [
    "EpicTaskGithubIssueSetRequest",
    "EpicTaskGithubIssueSetResponse",
    "handle_epic_task_github_issue_set",
]
