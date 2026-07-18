"""Create the next immutable annotated release tag for one project repo."""

from __future__ import annotations

import re
from typing import Any, List

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


_RELEASE_TAG_RE = re.compile(
    r"^v(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)\+launch\."
    r"(?P<sequence>0|[1-9][0-9]*)$"
)
_MAX_CREATE_ATTEMPTS = 4


class CreateNextReleaseTagRequest(BaseModel):
    repo: str = Field(..., min_length=3)
    project: str = Field(..., min_length=1)
    source_sha: str = Field(..., pattern=r"^[0-9a-f]{40}$")
    summary: str = Field(..., min_length=1, max_length=4000)


class CreateNextReleaseTagResponse(BaseModel):
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


def _release_refs(repo: str, token: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for page in range(1, 101):
        payload = rest_get(
            f"/repos/{repo}/git/matching-refs/tags/v"
            f"?per_page=100&page={page}",
            token=token,
        )
        if not isinstance(payload, list):
            raise RestTransportError(
                "matching release refs response must be a list"
            )
        refs.extend(row for row in payload if isinstance(row, dict))
        if len(payload) < 100:
            return refs
    raise RestTransportError("release ref inventory exceeded 100 pages")


def _tag_name(ref: dict[str, Any]) -> str:
    value = str(ref.get("ref") or "")
    prefix = "refs/tags/"
    return value[len(prefix):] if value.startswith(prefix) else ""


def _canonical_refs(
    refs: list[dict[str, Any]],
) -> list[tuple[tuple[int, int, int, int], str, dict[str, Any]]]:
    canonical = []
    for ref in refs:
        tag = _tag_name(ref)
        match = _RELEASE_TAG_RE.fullmatch(tag)
        if match is None:
            continue
        order = tuple(int(match.group(name)) for name in (
            "major", "minor", "patch", "sequence",
        ))
        canonical.append((order, tag, ref))
    return canonical


def _peeled_source(repo: str, ref: dict[str, Any], token: str) -> str:
    raw_object = ref.get("object")
    if not isinstance(raw_object, dict) or raw_object.get("type") != "tag":
        return ""
    tag_object_sha = str(raw_object.get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", tag_object_sha):
        return ""
    payload = rest_get(
        f"/repos/{repo}/git/tags/{tag_object_sha}",
        token=token,
    )
    if not isinstance(payload, dict):
        return ""
    target = payload.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit":
        return ""
    source_sha = str(target.get("sha") or "")
    return source_sha if re.fullmatch(r"[0-9a-f]{40}", source_sha) else ""


def _existing_tag_for_source(
    repo: str,
    canonical: list[tuple[tuple[int, int, int, int], str, dict[str, Any]]],
    source_sha: str,
    token: str,
) -> str:
    matches = [
        tag
        for _order, tag, ref in canonical
        if _peeled_source(repo, ref, token) == source_sha
    ]
    if len(matches) > 1:
        raise ValueError(
            "source commit has multiple canonical annotated release tags: "
            + ", ".join(sorted(matches))
        )
    return matches[0] if matches else ""


def _next_tag(
    canonical: list[tuple[tuple[int, int, int, int], str, dict[str, Any]]],
) -> str:
    if not canonical:
        raise ValueError(
            "no vX.Y.Z+launch.N release series exists; cut its first tag manually"
        )
    order, _tag, _ref = max(canonical, key=lambda row: row[0])
    major, minor, patch, sequence = order
    return f"v{major}.{minor}.{patch}+launch.{sequence + 1}"


def _require_source_commit(repo: str, source_sha: str, token: str) -> None:
    payload = rest_get(
        f"/repos/{repo}/git/commits/{source_sha}",
        token=token,
    )
    resolved_sha = (
        str(payload.get("sha") or "") if isinstance(payload, dict) else ""
    )
    if resolved_sha != source_sha:
        raise ValueError(
            f"source commit does not exist in the project repository: {source_sha}"
        )


def _create_annotated_tag(
    repo: str,
    tag: str,
    source_sha: str,
    summary: str,
    token: str,
) -> None:
    message = f"Yoke {tag.removeprefix('v')}\n\n{summary.strip()}"
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
        str(tag_object.get("sha") or "")
        if isinstance(tag_object, dict)
        else ""
    )
    if not re.fullmatch(r"[0-9a-f]{40}", tag_object_sha):
        raise RestTransportError("create annotated tag response omitted its SHA")
    rest_post(
        f"/repos/{repo}/git/refs",
        body={"ref": f"refs/tags/{tag}", "sha": tag_object_sha},
        token=token,
        max_attempts=1,
    )


def handle_create_next_release_tag(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        CreateNextReleaseTagRequest,
        "github.release.create_next_tag",
        required_permissions=GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS,
    )
    if error is not None:
        return error
    assert token is not None

    try:
        _require_source_commit(payload.repo, payload.source_sha, token)
        for attempt in range(_MAX_CREATE_ATTEMPTS):
            canonical = _canonical_refs(_release_refs(payload.repo, token))
            existing = _existing_tag_for_source(
                payload.repo, canonical, payload.source_sha, token,
            )
            if existing:
                return HandlerOutcome(
                    result_payload=CreateNextReleaseTagResponse(
                        tag=existing,
                        version=existing.removeprefix("v"),
                        source_sha=payload.source_sha,
                        created=False,
                    ).model_dump(),
                    primary_success=True,
                )
            tag = _next_tag(canonical)
            try:
                _create_annotated_tag(
                    payload.repo,
                    tag,
                    payload.source_sha,
                    payload.summary,
                    token,
                )
            except RestUnprocessableError:
                if attempt + 1 == _MAX_CREATE_ATTEMPTS:
                    raise
                continue
            return HandlerOutcome(
                result_payload=CreateNextReleaseTagResponse(
                    tag=tag,
                    version=tag.removeprefix("v"),
                    source_sha=payload.source_sha,
                    created=True,
                ).model_dump(),
                primary_success=True,
            )
    except ValueError as exc:
        return _failure("release_tag_invalid", str(exc))
    except RestTransportError as exc:
        return _transport_failed(f"create annotated release tag failed: {exc}")

    return _failure("release_tag_invalid", "release tag allocation did not finish")


REGISTRATIONS: List[dict[str, Any]] = [{
    "function_id": "github.release.create_next_tag",
    "handler": handle_create_next_release_tag,
    "request_model": CreateNextReleaseTagRequest,
    "response_model": CreateNextReleaseTagResponse,
    "stability": "stable",
    "owner_module": __name__,
    "target_kinds": ["global"],
    "side_effects": ["github_release_tag_create"],
    "emitted_event_names": [],
    "guardrails": [
        "project_auth_required",
        "api_token_actor_bound",
        "immutable_annotated_tag_only",
        "source_commit_exists",
    ],
    "adapter_status": "live",
    "claim_required_kind": None,
    "ambient_session_required": False,
}]


__all__ = [
    "CreateNextReleaseTagRequest",
    "CreateNextReleaseTagResponse",
    "REGISTRATIONS",
    "handle_create_next_release_tag",
]
