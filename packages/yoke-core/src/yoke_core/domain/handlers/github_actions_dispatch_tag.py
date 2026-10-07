"""Handler for ``github_actions.dispatch_tag.ensure``.

A ``workflow_dispatch`` runs the workflow file from the ref it is dispatched
at, and GitHub accepts only a branch or tag there, never a bare commit. A
deployment stage that must run its workflow from the release commit itself —
because the workflow builds and attests that commit, and its provenance names
the workflow source, the requested ref and the checkout as one commit — is
dispatched at a lightweight tag on that commit. This handler creates that tag,
or confirms it already names the commit.

Tags live only under :data:`DISPATCH_TAG_PREFIX`, so this create-only write
cannot move or mint any other tag in the repository. An existing tag naming a
different commit is refused, never moved.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport_errors import (
    RestTransportError,
    RestUnprocessableError,
)
from yoke_core.domain.github_actions_rest import rest_get, rest_post
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve,
)


FUNCTION_ID = "github_actions.dispatch_tag.ensure"

#: The only tag namespace this function writes; one tag per deployment run.
DISPATCH_TAG_PREFIX = "yoke-deploy/"

_TAG_NAME = re.compile(
    "^" + re.escape(DISPATCH_TAG_PREFIX) + r"[A-Za-z0-9][A-Za-z0-9._-]*$"
)


def dispatch_tag_name(run_id: str) -> str:
    """The tag a deployment run's stages are dispatched at."""
    return f"{DISPATCH_TAG_PREFIX}{run_id}"


class DispatchTagEnsureRequest(BaseModel):
    repo: str = Field(..., min_length=3, description="GitHub repo slug (owner/name).")
    project: str = Field(
        ..., min_length=1,
        description="Project capability owning the GitHub App repo binding.",
    )
    tag: str = Field(..., pattern=_TAG_NAME.pattern)
    sha: str = Field(..., pattern=r"^[0-9a-f]{40}$")


class DispatchTagEnsureResponse(BaseModel):
    repo: str
    tag: str
    sha: str
    created: bool


def _refused(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _tagged_commit(repo: str, tag: str, token: str) -> str | None:
    """The commit ``tag`` names, ``""`` for a non-commit tag, None when absent."""
    payload = rest_get(f"/repos/{repo}/git/ref/tags/{tag}", token=token)
    if not isinstance(payload, dict):
        return None
    target = payload.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit":
        return ""
    return str(target.get("sha") or "")


def _settled(repo: str, tag: str, sha: str, existing: str) -> HandlerOutcome:
    if existing == sha:
        return HandlerOutcome(
            result_payload=DispatchTagEnsureResponse(
                repo=repo, tag=tag, sha=sha, created=False,
            ).model_dump(),
            primary_success=True,
        )
    named = f"commit {existing}" if existing else "an annotated tag object"
    return _refused(
        "dispatch_tag_conflict",
        f"tag {tag} in {repo} already names {named}, not the run's bound "
        f"commit {sha}; Yoke never moves a dispatch tag. Find which control "
        f"plane created it (the run id is in the name); delete the tag in "
        f"{repo} only if no workflow run still refers to it, then re-drive "
        "the run",
    )


def handle_dispatch_tag_ensure(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, err = _validate_and_resolve(
        request,
        DispatchTagEnsureRequest,
        FUNCTION_ID,
        required_permissions=GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS,
    )
    if err is not None:
        return err
    assert token is not None
    repo, tag, sha = payload.repo, payload.tag, payload.sha

    try:
        existing = _tagged_commit(repo, tag, token)
        if existing is not None:
            return _settled(repo, tag, sha, existing)
        commit = rest_get(f"/repos/{repo}/git/commits/{sha}", token=token)
        if not isinstance(commit, dict) or commit.get("sha") != sha:
            return _refused(
                "dispatch_tag_commit_missing",
                f"commit {sha} does not exist in {repo}, so no workflow there "
                "can run from it; a stage that runs from the release commit "
                "must dispatch in the repository that holds that commit",
            )
        try:
            rest_post(
                f"/repos/{repo}/git/refs",
                body={"ref": f"refs/tags/{tag}", "sha": sha},
                token=token,
                max_attempts=1,
            )
        except RestUnprocessableError:
            # A concurrent ensure created it first; settle on what it wrote.
            existing = _tagged_commit(repo, tag, token)
            if existing is None:
                raise
            return _settled(repo, tag, sha, existing)
    except RestTransportError as exc:
        return _transport_failed(f"ensure dispatch tag {tag} failed: {exc}")

    return HandlerOutcome(
        result_payload=DispatchTagEnsureResponse(
            repo=repo, tag=tag, sha=sha, created=True,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_dispatch_tag_ensure,
        "request_model": DispatchTagEnsureRequest,
        "response_model": DispatchTagEnsureResponse,
        "stability": "stable",
        "owner_module": __name__,
        "target_kinds": ["global"],
        "side_effects": ["github_dispatch_tag_create"],
        "emitted_event_names": [],
        "guardrails": [
            "project_auth_required",
            "dispatch_tag_namespace_only",
            "existing_tag_never_moved",
            "source_commit_exists",
        ],
        "adapter_status": "live",
        "claim_required_kind": None,
        "minimum_serving_version": "next-release",
    },
]


__all__ = [
    "DISPATCH_TAG_PREFIX",
    "DispatchTagEnsureRequest",
    "DispatchTagEnsureResponse",
    "FUNCTION_ID",
    "REGISTRATIONS",
    "dispatch_tag_name",
    "handle_dispatch_tag_ensure",
]
