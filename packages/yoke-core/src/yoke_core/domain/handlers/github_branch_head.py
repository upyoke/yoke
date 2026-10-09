"""Read one branch's current head, and whether it descends from a commit.

A release that proved a pair against one commit of another project needs to
know, right before it hands that proof on, whether the other project's branch
still names that commit — and when it does not, whether the branch only moved
forward from it or was rewritten. The caller holds no checkout of that
project and no credential for its repository, so the read happens where the
project's own repository binding is: the control plane.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve_auth,
)


OWNER_MODULE = "yoke_core.domain.handlers.github_branch_head"
FUNCTION_ID = "github.branch.head"

#: ``since`` is the head itself.
RELATION_IDENTICAL = "identical"
#: The head descends from ``since``: the branch only moved forward.
RELATION_DESCENDANT = "descendant"
#: ``since`` is not an ancestor of the head: the branch was rewritten, or
#: moved back.
RELATION_NOT_DESCENDANT = "not_descendant"


class BranchHeadRequest(BaseModel):
    project: str = Field(..., min_length=1)
    branch: str = Field(..., min_length=1)
    # A full commit the caller already holds; when given, the answer says
    # how the head relates to it.
    since: Optional[str] = Field(None, pattern=r"^[0-9a-fA-F]{40}$")


class BranchHeadResponse(BaseModel):
    repo: str
    branch: str
    head_sha: str
    since: str = ""
    relation: str = ""


def handle_branch_head(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the branch's head commit and, with ``since``, its ancestry."""
    payload, resolved, error = _validate_and_resolve_auth(
        request,
        BranchHeadRequest,
        FUNCTION_ID,
        required_permissions=GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
    )
    if error is not None:
        return error
    assert payload is not None and resolved is not None

    from yoke_core.domain.deployment_run_carried_work_repository import (
        RepositoryProviderSource,
    )
    from yoke_core.domain.deployment_run_carried_work_source import (
        CarriedWorkSourceUnavailable,
    )

    repo = str(resolved.repo or "").strip()
    if not repo:
        return _transport_failed(
            "the project's GitHub binding names no repository to read a branch from"
        )
    branch = payload.branch.strip()
    source = RepositoryProviderSource(repo, resolved.token)
    head = source.resolve_commit(branch)
    if not head:
        return _transport_failed(
            f"branch '{branch}' of {repo} resolved no commit; check that the "
            "branch exists and the project's GitHub binding can read contents"
        )
    since = str(payload.since or "").strip().lower()
    relation = ""
    if since:
        if since == head:
            relation = RELATION_IDENTICAL
        else:
            try:
                # The head contains ``since`` exactly when ``since`` is one of
                # its ancestors.
                contains = source.contains_commit(head, since)
            except CarriedWorkSourceUnavailable as exc:
                return _transport_failed(
                    f"ancestry of {head} over {since} in {repo} could not be "
                    f"read: {exc.reason}: {exc.recovery}"
                )
            if contains is None:
                return _transport_failed(
                    f"the comparison of {since}...{head} in {repo} named no "
                    "ancestry; retry the read"
                )
            relation = RELATION_DESCENDANT if contains else RELATION_NOT_DESCENDANT
    return HandlerOutcome(
        result_payload=BranchHeadResponse(
            repo=repo,
            branch=branch,
            head_sha=head,
            since=since,
            relation=relation,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_branch_head,
        "request_model": BranchHeadRequest,
        "response_model": BranchHeadResponse,
        "stability": "stable",
        "owner_module": OWNER_MODULE,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
        "minimum_serving_version": "next-release",
    },
]


__all__ = [
    "FUNCTION_ID",
    "REGISTRATIONS",
    "RELATION_DESCENDANT",
    "RELATION_IDENTICAL",
    "RELATION_NOT_DESCENDANT",
    "BranchHeadRequest",
    "BranchHeadResponse",
    "handle_branch_head",
]
