"""Typed project-scoped creation and shared completion of Inbox posts."""

from typing import Any

from pydantic import BaseModel, Field, ConfigDict

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.db_savepoint import SavepointLostError
from yoke_core.domain.handlers.inbox_decisions import _actor_id, _error, _require_global


class PostCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    title: str = Field(min_length=1, max_length=300)
    body: str
    source: str = Field(min_length=1, max_length=100)
    fields: dict[str, Any] = Field(default_factory=dict)
    audience_id: int | None = None
    audience_name: str | None = None
    rules: list[dict[str, Any]] | None = None


class PostDoneRequest(BaseModel):
    post_id: int


class PostResponse(BaseModel):
    post: dict[str, Any]


def _handle(request: FunctionCallRequest, model_type, operation) -> HandlerOutcome:
    invalid = _require_global(request, request.function)
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, request.function)
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    from yoke_core.domain.db_helpers import connect

    try:
        model = model_type.model_validate(request.payload or {})
        with connect() as conn:
            result = operation(conn, actor_id, model)
    except SavepointLostError:
        raise
    except (ValueError, LookupError, PermissionError) as exc:
        code = (
            "permission_denied"
            if isinstance(exc, PermissionError)
            else str(exc).split(":", 1)[0]
        )
        return _error(code, str(exc))
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_create(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.inbox_posts import create_post

    return _handle(
        request,
        PostCreateRequest,
        lambda conn, actor, model: {
            "post": create_post(conn, actor_id=actor, **model.model_dump()),
        },
    )


def handle_done(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.inbox_posts import done_post

    return _handle(
        request,
        PostDoneRequest,
        lambda conn, actor, model: {
            "post": done_post(conn, actor_id=actor, post_id=model.post_id),
        },
    )


def register(registry) -> None:
    for function_id, handler, model in (
        ("inbox.posts.create", handle_create, PostCreateRequest),
        ("inbox.posts.done", handle_done, PostDoneRequest),
    ):
        registry.register(
            function_id,
            handler,
            model,
            PostResponse,
            stability="stable",
            owner_module=__name__,
            target_kinds=["global"],
            side_effects=["inbox_posts_write"],
            emitted_event_names=[],
            guardrails=["project_permission", "live_audience"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
            minimum_serving_version="next-release",
        )
