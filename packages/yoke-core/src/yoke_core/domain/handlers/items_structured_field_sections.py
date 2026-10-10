"""Section-upsert handler and its field-targeted receipt."""

from yoke_core.domain import item_field_transform
from yoke_core.domain.handlers.items_structured_field_models import (
    SectionUpsertRequest,
    SectionUpsertResponse,
)
from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome


def handle_section_upsert(request: FunctionCallRequest) -> HandlerOutcome:
    """Upsert a rendered section via ``item_field_transform.section_upsert``."""
    from yoke_core.domain.handlers.items_structured_field import (
        _require_item_target,
        _bad_request,
        _guard_failed,
        _classify_write_error,
        _github_sync_warnings,
    )

    item_id = _require_item_target(request)
    if item_id is None:
        return _bad_request("target must carry kind='item' and public_ref (PREFIX-N)")
    try:
        payload = SectionUpsertRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")

    result = item_field_transform.section_upsert(
        item_id=item_id,
        section=payload.section,
        content=payload.content,
        ordering=payload.ordering,
        source=payload.source,
        field=payload.field,
        heading_level=payload.heading_level,
    )
    if not result.success:
        return _guard_failed(
            _classify_write_error(result.error),
            result.error or "section_upsert failed",
        )

    response = SectionUpsertResponse(
        field=payload.field,
        heading_level=payload.heading_level if payload.field else None,
        item_id=item_id,
        section=payload.section,
        changed=result.changed,
        new_line_count=result.new_line_count,
        verification=result.verification,
    )
    return HandlerOutcome(
        result_payload=response.model_dump(exclude_none=True),
        primary_success=True,
        warnings=_github_sync_warnings(result.warning),
    )
