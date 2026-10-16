"""Create an immutable annotated tag derived from its source commit's UTC clock."""

from __future__ import annotations

from datetime import datetime

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.release_version import commit_version
from yoke_core.domain.gh_rest_transport_errors import (
    RestTransportError,
    RestUnprocessableError,
)
from yoke_core.domain.github_actions_rest import rest_get
from yoke_core.domain.handlers.github_actions_set import (
    _transport_failed,
    _validate_and_resolve,
)
from yoke_core.domain.handlers.github_release_tag import (
    CreateReleaseTagRequest,
    CreateReleaseTagResponse,
    _create_annotated_tag,
    _failure,
)


def _existing(repo: str, tag: str, source: str, token: str) -> bool:
    ref = rest_get(f"/repos/{repo}/git/ref/tags/{tag}", token=token)
    if ref is None:
        return False
    obj = ref.get("object", {}) if isinstance(ref, dict) else {}
    if obj.get("type") != "tag":
        raise ValueError("release_tag_collision: existing ref is not annotated")
    annotated = rest_get(f"/repos/{repo}/git/tags/{obj.get('sha')}", token=token)
    target = annotated.get("object", {}) if isinstance(annotated, dict) else {}
    if (
        annotated.get("tag") != tag
        or target.get("type") != "commit"
        or target.get("sha") != source
    ):
        raise ValueError(
            "release_tag_collision: UTC minute already names a different commit; "
            "create a new source commit with a distinct UTC minute and retry"
        )
    return True


def handle_create_commit_release_tag(request: FunctionCallRequest) -> HandlerOutcome:
    payload, token, error = _validate_and_resolve(
        request,
        CreateReleaseTagRequest,
        "github.release.create_commit_tag",
        required_permissions=GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS,
    )
    if error is not None:
        return error
    assert token is not None
    try:
        source = rest_get(
            f"/repos/{payload.repo}/git/commits/{payload.source_sha}",
            token=token,
        )
        if not isinstance(source, dict) or source.get("sha") != payload.source_sha:
            raise ValueError(
                "release_source_invalid: fetch the exact repository commit and retry"
            )
        clock = source.get("committer", {}).get("date", "")
        tag = commit_version(datetime.fromisoformat(clock.replace("Z", "+00:00")))
        created = False
        if not _existing(payload.repo, tag, payload.source_sha, token):
            try:
                _create_annotated_tag(
                    payload.repo,
                    tag,
                    payload.source_sha,
                    payload.summary,
                    token,
                )
                created = True
            except RestUnprocessableError:
                if not _existing(payload.repo, tag, payload.source_sha, token):
                    raise
        return HandlerOutcome(
            result_payload=CreateReleaseTagResponse(
                tag=tag,
                version=tag,
                source_sha=payload.source_sha,
                created=created,
            ).model_dump(),
            primary_success=True,
        )
    except (ValueError, TypeError, AttributeError) as exc:
        code = (
            "release_tag_collision"
            if str(exc).startswith("release_tag_collision:")
            else "release_identity_invalid"
        )
        return _failure(
            code, f"{exc}; inspect the source commit and immutable tag before retrying"
        )
    except RestTransportError as exc:
        return _transport_failed(
            f"commit release tag unavailable: {exc}; restore repository access and retry the same source"
        )


REGISTRATIONS = [
    {
        "function_id": "github.release.create_commit_tag",
        "handler": handle_create_commit_release_tag,
        "request_model": CreateReleaseTagRequest,
        "response_model": CreateReleaseTagResponse,
        "minimum_serving_version": "next-release",
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
    }
]
