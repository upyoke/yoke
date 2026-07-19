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
_MAX_RELEASE_REF_PAGES = 100
_RELEASE_REFS_QUERY = """
query ReleaseTags($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: "refs/tags/", first: 100, after: $cursor) {
      nodes {
        name
        target {
          __typename
          ... on Tag {
            target {
              __typename
              ... on Commit { oid }
            }
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


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
    owner, separator, name = repo.partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ValueError(f"repo must be owner/name, got {repo!r}")
    refs: list[dict[str, Any]] = []
    cursor: str | None = None
    for _page in range(_MAX_RELEASE_REF_PAGES):
        payload = rest_post(
            "/graphql",
            body={
                "query": _RELEASE_REFS_QUERY,
                "variables": {
                    "owner": owner,
                    "name": name,
                    "cursor": cursor,
                },
            },
            token=token,
        )
        if not isinstance(payload, dict) or payload.get("errors"):
            raise RestTransportError("release tag GraphQL response was invalid")
        data = payload.get("data")
        repository = data.get("repository") if isinstance(data, dict) else None
        connection = (
            repository.get("refs") if isinstance(repository, dict) else None
        )
        nodes = connection.get("nodes") if isinstance(connection, dict) else None
        page_info = (
            connection.get("pageInfo") if isinstance(connection, dict) else None
        )
        if not isinstance(nodes, list) or not isinstance(page_info, dict):
            raise RestTransportError("release tag GraphQL response was incomplete")
        for node in nodes:
            if not isinstance(node, dict):
                continue
            target = node.get("target")
            annotated_target = (
                target.get("target") if isinstance(target, dict) else None
            )
            source_sha = (
                str(annotated_target.get("oid") or "")
                if isinstance(annotated_target, dict)
                and target.get("__typename") == "Tag"
                and annotated_target.get("__typename") == "Commit"
                else ""
            )
            refs.append(
                {
                    "ref": f"refs/tags/{str(node.get('name') or '')}",
                    "source_sha": source_sha,
                }
            )
        if not page_info.get("hasNextPage"):
            return refs
        next_cursor = page_info.get("endCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            raise RestTransportError("release tag GraphQL pagination omitted a cursor")
        cursor = next_cursor
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


def _peeled_source(ref: dict[str, Any]) -> str:
    source_sha = str(ref.get("source_sha") or "")
    return source_sha if re.fullmatch(r"[0-9a-f]{40}", source_sha) else ""


def _existing_tag_for_source(
    canonical: list[tuple[tuple[int, int, int, int], str, dict[str, Any]]],
    source_sha: str,
) -> str:
    matches = [
        tag
        for _order, tag, ref in canonical
        if _peeled_source(ref) == source_sha
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
                canonical, payload.source_sha,
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
