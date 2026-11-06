"""Handler for ``github.merge_queue.apply`` — converge declared merge-queue config.

Reads the landed gate declaration, checks any transported content matches,
and idempotently PUTs the ruleset plus
``allow_auto_merge`` onto the project's bound GitHub repository. Requires
Administration: write on the App (privileged opt-in), matching environment
create.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS,
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers.github_actions_set import (
    _auth_failed,
    _bad_request,
    _transport_failed,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class MergeQueueApplyRequest(BaseModel):
    project: str = Field(
        ...,
        min_length=1,
        description="Project owning the GitHub repo binding.",
    )
    declaration: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Parsed declaration content transported by the client. "
            "Omit it to use the landed gate declaration."
        ),
    )
    preview: bool = Field(
        False,
        description="Report planned mutations without writing to GitHub.",
    )


class MergeQueueApplyResponse(BaseModel):
    preview: bool
    owner: str
    repo: str
    ruleset_name: str
    ruleset_id: Optional[int] = None
    actions: List[str]
    changed: bool
    drift_before: List[str] = Field(default_factory=list)
    remaining_drift: List[str] = Field(default_factory=list)


def handle_merge_queue_apply(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _bad_request(
            "target.kind must be 'global'",
            jsonpath="$.target.kind",
        )
    try:
        payload = MergeQueueApplyRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _bad_request(safe_validation_message(exc))

    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(
            payload.project,
            required_permissions={
                **GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS,
                **GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
            },
        )
    except ProjectGithubAuthError as exc:
        return _auth_failed(exc, payload.project)

    from yoke_core.domain import gh_rest_transport
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.merge_queue_declaration import (
        DECLARATION_RELATIVE_PATH,
        MergeQueueDeclarationError,
        parse_declaration,
        validate_declaration,
    )
    from yoke_core.domain.merge_queue_declaration_apply import (
        apply_declaration,
    )
    from yoke_contracts.refusal_recovery import compose_refusal
    from yoke_core.domain import github_merge_queue_rest as mq_rest
    from yoke_core.domain.db_helpers import connect, query_scalar
    from yoke_core.domain.db_backend import connection_is_postgres

    owner, repo = gh_rest_transport.split_repo(resolved.repo)
    landed = None
    branch = ""
    if not payload.preview or payload.declaration is None:
        with closing(connect()) as conn:
            marker = "%s" if connection_is_postgres(conn) else "?"
            branch = query_scalar(
                conn, f"SELECT default_branch FROM projects WHERE slug = {marker}",
                (resolved.project,),
            )
        if not branch:
            return _bad_request(compose_refusal(
                "gate_branch_unspecified",
                recovery="Set the project's default_branch, then retry apply",
            ))
        try:
            raw = mq_rest.fetch_file_text(
                owner, repo, DECLARATION_RELATIVE_PATH, ref=str(branch), token=resolved.token,
            )
            if raw is None:
                raise MergeQueueDeclarationError(f"no gate declaration on {branch}")
            landed = parse_declaration(raw, source=f"{owner}/{repo}@{branch}")
        except (RestTransportError, MergeQueueDeclarationError) as exc:
            return _bad_request(compose_refusal(
                f"gate_declaration_unverified: {exc}",
                recovery="Restore Contents: read and a valid gate declaration, then retry apply",
            ))

    declared = landed
    if payload.declaration is not None:
        try:
            declared = validate_declaration(
                payload.declaration,
                source="merge-queue declaration payload",
            )
        except MergeQueueDeclarationError as exc:
            return _bad_request(str(exc))
    if not payload.preview and declared != landed:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="declaration_not_landed",
                message=compose_refusal(
                    f"declaration_not_landed: sent content differs from {branch}",
                    recovery=("land the declaration change first, then apply. To remove or "
                              "rename a required check, use two PRs: land and apply the "
                              "declaration change, then remove or rename the CI job"),
                ),
                jsonpath="$.payload.declaration",
            ),
        )
    try:
        result = apply_declaration(
            declared,
            owner=owner,
            repo=repo,
            token=resolved.token,
            preview=payload.preview,
        )
    except RestTransportError as exc:
        return _transport_failed(f"merge_queue apply failed: {exc}")

    response = MergeQueueApplyResponse.model_validate(result)
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github.merge_queue.apply",
        "handler": handle_merge_queue_apply,
        "request_model": MergeQueueApplyRequest,
        "response_model": MergeQueueApplyResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_merge_queue_apply",
        "target_kinds": ["global"],
        "side_effects": ["github_merge_queue_apply"],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "MergeQueueApplyRequest",
    "MergeQueueApplyResponse",
    "REGISTRATIONS",
    "handle_merge_queue_apply",
]
