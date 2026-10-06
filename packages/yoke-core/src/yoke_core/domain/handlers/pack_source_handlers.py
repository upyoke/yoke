"""Registered handler rendering a Pack bundle from submitted pre-release source."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers.pack_handlers import (
    PacksBundleGetResponse,
    _failure,
    _invalid,
)
from yoke_core.domain.pack_catalog import PackError
from yoke_core.domain.pack_submitted_source import render_submitted_pack_bundle


class SubmittedPackFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str


class PacksBundleRenderRequest(BaseModel):
    """One Pack's ``packs/``-relative source tree, read by the client."""

    model_config = ConfigDict(extra="forbid")

    project: str
    pack: str
    source: dict[str, Any]
    files: list[SubmittedPackFile]
    version: str | None = None
    render_values: dict[str, str] | None = None


class PacksBundleRenderResponse(PacksBundleGetResponse):
    catalog: dict[str, str]


def handle_packs_bundle_render(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = PacksBundleRenderRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        result = render_submitted_pack_bundle(
            conn,
            project=parsed.project,
            pack=parsed.pack,
            source=parsed.source,
            files=[row.model_dump() for row in parsed.files],
            version=parsed.version,
            render_values=parsed.render_values,
        )
    except (LookupError, PackError) as exc:
        return _failure("pack_bundle_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "PacksBundleRenderRequest",
    "PacksBundleRenderResponse",
    "handle_packs_bundle_render",
]
