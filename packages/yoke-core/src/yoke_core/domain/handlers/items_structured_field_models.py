"""Pydantic request / response models for ``items.structured_field.*``.

Sibling of :mod:`yoke_core.domain.handlers.items_structured_field`.
Owns the typed boundary contracts so the handler dispatch module stays
under the 350-line file budget.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ReplaceRequest(BaseModel):
    field: str
    content: str = ""
    source: str = ""
    force: bool = False


class ReplaceResponse(BaseModel):
    item_id: int
    field: str
    old_line_count: int
    new_line_count: int
    old_hash: str
    new_hash: str
    payload_byte_count: int
    empty_payload: bool
    verification: str
    github_sync: str


class AppendAddendumRequest(BaseModel):
    field: str
    heading: str
    content: str
    source: str = ""


class AppendAddendumResponse(BaseModel):
    item_id: int
    field: str
    heading: str
    changed: bool
    old_line_count: int
    new_line_count: int
    verification: str


class SectionUpsertRequest(BaseModel):
    section: str
    content: str
    ordering: Optional[int] = None
    source: Optional[str] = None


class SectionUpsertResponse(BaseModel):
    item_id: int
    section: str
    changed: bool
    new_line_count: int
    verification: str


class SectionAppendRequest(BaseModel):
    section: str
    headline: str
    content: str
    ordering: Optional[int] = None
    source: Optional[str] = None


class SectionAppendResponse(BaseModel):
    item_id: int
    section: str
    changed: bool
    old_line_count: int
    new_line_count: int
    verification: str


def build_registrations():
    """Compose the four ``items.structured_field.*`` registration dicts.

    Imported lazily inside ``register_all_handlers`` (and at module
    import here is fine because handler imports are deferred to call
    time) to avoid a circular import between this module (which the
    handler module imports for its Pydantic models) and the handler
    module (which exposes the callables).
    """
    from yoke_core.domain.handlers.items_structured_field import (
        handle_append_addendum, handle_replace,
        handle_section_append, handle_section_upsert,
    )

    owner = "yoke_core.domain.handlers.items_structured_field"
    side_effects = ["render_body", "github_sync", "rebuild_board"]
    guardrails = ["empty_body", "shrinkage", "freeze_lock", "invalid_field"]

    return [
        {
            "function_id": "items.structured_field.replace",
            "handler": handle_replace,
            "request_model": ReplaceRequest,
            "response_model": ReplaceResponse,
            "stability": "stable",
            "owner_module": owner,
            "target_kinds": ["item"],
            "side_effects": list(side_effects),
            "emitted_event_names": ["StructuredFieldWritten"],
            "guardrails": list(guardrails),
            "adapter_status": "live",
            "claim_required_kind": "item",
        },
        {
            "function_id": "items.structured_field.append_addendum",
            "handler": handle_append_addendum,
            "request_model": AppendAddendumRequest,
            "response_model": AppendAddendumResponse,
            "stability": "stable",
            "owner_module": owner,
            "target_kinds": ["item"],
            "side_effects": list(side_effects),
            "emitted_event_names": ["StructuredFieldAddendumAppended"],
            "guardrails": list(guardrails),
            "adapter_status": "live",
            "claim_required_kind": "item",
        },
        {
            "function_id": "items.structured_field.section_upsert",
            "handler": handle_section_upsert,
            "request_model": SectionUpsertRequest,
            "response_model": SectionUpsertResponse,
            "stability": "stable",
            "owner_module": owner,
            "target_kinds": ["item"],
            "side_effects": list(side_effects),
            "emitted_event_names": ["SectionUpserted"],
            "guardrails": [],
            "adapter_status": "live",
            "claim_required_kind": "item",
        },
        {
            "function_id": "items.structured_field.section_append",
            "handler": handle_section_append,
            "request_model": SectionAppendRequest,
            "response_model": SectionAppendResponse,
            "stability": "stable",
            "owner_module": owner,
            "target_kinds": ["item"],
            "side_effects": list(side_effects),
            "emitted_event_names": ["SectionAppended"],
            "guardrails": [],
            "adapter_status": "live",
            "claim_required_kind": "item",
        },
    ]


__all__ = [
    "ReplaceRequest", "ReplaceResponse",
    "AppendAddendumRequest", "AppendAddendumResponse",
    "SectionUpsertRequest", "SectionUpsertResponse",
    "SectionAppendRequest", "SectionAppendResponse",
    "build_registrations",
]
