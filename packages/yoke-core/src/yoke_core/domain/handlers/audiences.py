"""Create and select reusable project audiences."""

from typing import Any

from pydantic import BaseModel, Field

from yoke_core.domain import audiences
from yoke_core.domain.actor_permissions import PERM_ITEMS_READ, PERM_ITEMS_WRITE
from yoke_core.domain.handlers.inbox_posts import _handle
from yoke_core.domain.inbox_posts import _permission


class AudienceListRequest(BaseModel):
    project_id: int


class AudienceCreateRequest(AudienceListRequest):
    name: str = Field(min_length=1, max_length=100)
    rules: list[dict[str, Any]]


class AudienceResponse(BaseModel):
    audiences: list[dict[str, Any]]


def handle_create(request):
    def create(conn, actor, model):
        _permission(conn, actor, model.project_id, PERM_ITEMS_WRITE)
        audience_id = audiences.create_audience(conn, **model.model_dump())
        return {"audiences": [audiences.audience(conn, audience_id)]}

    return _handle(request, AudienceCreateRequest, create)


def handle_list(request):
    def read(conn, actor, model):
        _permission(conn, actor, model.project_id, PERM_ITEMS_READ)
        return {
            "audiences": audiences.named_audiences(conn, project_id=model.project_id)
        }

    return _handle(request, AudienceListRequest, read)


def register(registry):
    for function_id, handler, model, effects in (
        (
            "audiences.create",
            handle_create,
            AudienceCreateRequest,
            ["audiences_insert"],
        ),
        ("audiences.list", handle_list, AudienceListRequest, []),
    ):
        registry.register(
            function_id,
            handler,
            model,
            AudienceResponse,
            stability="stable",
            owner_module=__name__,
            target_kinds=["global"],
            side_effects=effects,
            emitted_event_names=[],
            guardrails=["project_permission", "validated_rules"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
            minimum_serving_version="next-release",
        )
