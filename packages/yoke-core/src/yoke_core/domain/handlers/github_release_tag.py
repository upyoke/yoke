"""Annotated release tag payloads and immutable GitHub write primitive."""

from __future__ import annotations

import re
from pydantic import BaseModel, Field
from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.gh_rest_transport_errors import RestTransportError
from yoke_core.domain.github_actions_rest import rest_post


class CreateReleaseTagRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    project: str = Field(..., min_length=1)
    source_sha: str = Field(..., pattern=r"^[0-9a-f]{40}$")
    summary: str = Field(..., min_length=1, max_length=4000)


class CreateReleaseTagResponse(BaseModel):
    tag: str
    version: str
    source_sha: str
    created: bool


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _create_annotated_tag(
    repo: str,
    tag: str,
    source_sha: str,
    summary: str,
    token: str,
) -> None:
    message = f"Yoke {tag}\n\n{summary.strip()}"
    tag_object = rest_post(
        f"/repos/{repo}/git/tags",
        body={
            "tag": tag,
            "message": message,
            "object": source_sha,
            "type": "commit",
        },
        token=token,
        max_attempts=1,
    )
    tag_object_sha = (
        str(tag_object.get("sha") or "") if isinstance(tag_object, dict) else ""
    )
    if not re.fullmatch(r"[0-9a-f]{40}", tag_object_sha):
        raise RestTransportError("create annotated tag response omitted its SHA")
    rest_post(
        f"/repos/{repo}/git/refs",
        body={"ref": f"refs/tags/{tag}", "sha": tag_object_sha},
        token=token,
        max_attempts=1,
    )
