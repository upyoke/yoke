"""Handler for ``github.merge_queue.apply`` — converge declared merge-queue config.

Accepts transported declaration content, or reads the project checkout for
an in-process caller that omitted it, and idempotently PUTs the ruleset plus
``allow_auto_merge`` onto the project's bound GitHub repository. Requires
Administration: write on the App (privileged opt-in), matching environment
create.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS,
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
            "In-process callers may omit it to use the project checkout."
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
        repair_command_hint,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(
            payload.project,
            required_permissions=GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        return _auth_failed(
            f"{exc.code}: {exc}",
            repair_hint=repair_command_hint(exc, payload.project),
        )

    from yoke_core.domain import gh_rest_transport
    from yoke_core.domain.gh_rest_transport import RestTransportError
    from yoke_core.domain.merge_queue_declaration import (
        DECLARATION_RELATIVE_PATH,
        MergeQueueDeclarationError,
        load_declaration,
        validate_declaration,
    )
    from yoke_core.domain.merge_queue_declaration_apply import (
        apply_declaration,
    )
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_slug,
    )

    if payload.declaration is not None:
        try:
            declared = validate_declaration(
                payload.declaration,
                source="merge-queue declaration payload",
            )
        except MergeQueueDeclarationError as exc:
            return _bad_request(str(exc))
    else:
        checkout = checkout_for_project_slug(payload.project)
        if checkout is None:
            return _bad_request(
                f"no local checkout mapped for project {payload.project!r}; "
                "transport declaration content or register the checkout"
            )
        path = Path(checkout) / DECLARATION_RELATIVE_PATH
        try:
            declared = load_declaration(path)
        except MergeQueueDeclarationError as exc:
            return _bad_request(str(exc))

    owner, repo = gh_rest_transport.split_repo(resolved.repo)
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
