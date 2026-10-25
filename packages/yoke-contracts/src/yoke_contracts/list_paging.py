"""Shared limit/offset paging for list reads."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

DEFAULT_LIST_LIMIT = 25
MAX_LIST_LIMIT = 500


class ListPageRequest(BaseModel):
    # Programmatic readers may enumerate the whole collection. CLI readers
    # always name a limit, independently of detail selection.
    limit: int | None = Field(default=None, ge=1, le=MAX_LIST_LIMIT)
    offset: int = Field(default=0, ge=0)


class ListPageResponse(BaseModel):
    limit: int | None = None
    offset: int = 0
    next_offset: int | None = None


def page_result(result: dict[str, Any], key: str, payload: dict) -> dict:
    """Page an ordered collection without changing its surrounding facts."""
    page = ListPageRequest.model_validate(payload)
    rows = result[key]
    stop = page.offset + page.limit if page.limit is not None else None
    selected = rows[page.offset : stop]
    return {
        **result,
        key: selected,
        "limit": page.limit,
        "offset": page.offset,
        "next_offset": page.offset + len(selected)
        if stop is not None and stop < len(rows)
        else None,
    }
