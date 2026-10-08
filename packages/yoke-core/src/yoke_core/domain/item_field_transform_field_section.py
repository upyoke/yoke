"""Replace a rendered section inside its owning structured field."""

from typing import Optional, TYPE_CHECKING
from yoke_core.domain.render_body_section import has_top_level_section, replace_section

if TYPE_CHECKING:
    from yoke_core.domain.item_field_transform import TransformResult


def _section_upsert_in_field(
    *,
    item_id: int,
    section: str,
    heading_norm: str,
    field: str,
    field_content: str,
    new_section_content: str,
    source: Optional[str],
) -> "TransformResult":
    from yoke_core.domain.item_field_transform_sections import (
        SECTION_UPSERT,
        _result,
        _line_count,
        _read_field,
        _NullSink,
    )
    from yoke_core.domain.backlog_structured_write_op import (
        execute_structured_write,
    )

    base = dict(
        operation=SECTION_UPSERT,
        item_id=item_id,
        section=section,
        field=field,
    )
    old_lines = _line_count(field_content)
    new_field_content = replace_section(
        field_content,
        heading_norm,
        new_section_content,
    )
    if new_field_content is None:
        return _result(
            success=False,
            error=f"section '{heading_norm}' disappeared before replacement",
            verification="missing",
            old_line_count=old_lines,
            **base,
        )
    write_result = execute_structured_write(
        item_id=item_id,
        field=field,
        content=new_field_content,
        source=source or "",
        out=_NullSink(),
    )
    if not write_result.get("success"):
        err = str(write_result.get("error") or "structured write failed")
        return _result(success=False, error=err, old_line_count=old_lines, **base)
    persisted = _read_field(item_id, field) or ""
    new_lines = _line_count(persisted)
    if not has_top_level_section(persisted, heading_norm):
        return _result(
            success=False,
            error=f"post-write verification failed: heading missing in '{field}'",
            verification="missing",
            old_line_count=old_lines,
            new_line_count=new_lines,
            **base,
        )
    return _result(
        success=True,
        changed=True,
        old_line_count=old_lines,
        new_line_count=new_lines,
        verification="ok",
        warning=str(write_result.get("sync_warning") or ""),
        **base,
    )
