"""Pydantic request/response models for the ``strategy.doc.*`` family.

Split from :mod:`yoke_core.domain.handlers.strategy_docs` (which owns
the handlers and registrations) to respect the authored-file line cap.
Every response carries ``project_id``/``project_slug`` so callers can
see which project's corpus served the call.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class DocListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocListResponse(BaseModel):
    project_id: int
    project_slug: str
    docs: List[Dict[str, Any]] = Field(default_factory=list)


class DocGetRequest(BaseModel):
    slug: str = Field(..., min_length=1, description="Strategy doc slug.")


class DocGetResponse(BaseModel):
    project_id: int
    project_slug: str
    slug: str
    content: str
    updated_at: str


class DocReplaceRequest(BaseModel):
    slug: str = Field(..., min_length=1, description="Strategy doc slug.")
    content: str = Field(
        ...,
        description=(
            "Full replacement content. May be header-free body or a rendered "
            ".yoke/strategy/<slug>.md file; a valid generated header is "
            "ignored before storage."
        ),
    )
    base_updated_at: str = Field(
        ..., min_length=1,
        description=(
            "The row updated_at this content was authored against (from "
            "strategy.doc.get); the write is compare-and-swap on it."
        ),
    )
    force: bool = Field(
        False, description="Bypass the shrink guard for an intentional rewrite.",
    )


class DocReplaceResponse(BaseModel):
    project_id: int
    project_slug: str
    slug: str
    old_bytes: int
    new_bytes: int
    updated_at: str
    # True when the new content was byte-identical to the stored content, so
    # the row was NOT written (updated_at/updated_by preserved). Keeps the
    # rendered view from churning on a no-op write.
    unchanged: bool = False


class RenderRequest(BaseModel):
    # File I/O is the caller's (12942): the handler returns rendered
    # file texts and the CLI writes them into the checkout it resolved
    # client-side. A stray legacy ``target_root`` field is ignored.
    slugs: List[str] = Field(
        default_factory=list,
        description="Doc slugs to render; empty means the project's full corpus.",
    )


class RenderResponse(BaseModel):
    project_id: int
    project_slug: str
    docs: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-doc {slug, updated_at, file_text} render map.",
    )


__all__ = [
    "DocGetRequest",
    "DocGetResponse",
    "DocListRequest",
    "DocListResponse",
    "DocReplaceRequest",
    "DocReplaceResponse",
    "RenderRequest",
    "RenderResponse",
]
