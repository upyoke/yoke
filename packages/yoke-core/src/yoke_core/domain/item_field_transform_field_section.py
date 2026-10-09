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


def _subtree_spans(text: str, section: str, depth: int) -> list[tuple[int, int]]:
    """Locate every matching ATX subtree outside Markdown code fences."""
    import re

    headings = []
    offset = 0
    fence = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", stripped)
        if fence:
            if (
                marker
                and marker[1][0] == fence
                and len(marker[1]) >= fence_length
                and not marker[2].strip()
            ):
                fence = ""
        elif marker:
            fence, fence_length = marker[1][0], len(marker[1])
        else:
            heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*$", stripped)
            if heading:
                title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2])
                headings.append((offset, len(heading[1]), title))
        offset += len(line)
    spans = []
    for index, (start, level, title) in enumerate(headings):
        if level == depth and title == section.strip():
            end = next(
                (
                    pos
                    for pos, next_level, _ in headings[index + 1 :]
                    if next_level <= depth
                ),
                len(text),
            )
            spans.append((start, end))
    return spans


def upsert_field_subtree(
    *,
    item_id: int,
    field: str,
    section: str,
    content: str,
    heading_level: int,
    source: Optional[str],
) -> "TransformResult":
    from yoke_core.domain.item_field_transform_sections import (
        SECTION_UPSERT,
        _result,
        _line_count,
        _read_field,
        _NullSink,
    )
    from yoke_core.domain.backlog_structured_write_op import execute_structured_write

    existing = _read_field(item_id, field) or ""
    base = dict(
        operation=SECTION_UPSERT,
        item_id=item_id,
        field=field,
        section=section,
        heading_level=heading_level,
        old_line_count=_line_count(existing),
    )
    spans = _subtree_spans(existing, section, heading_level)
    if len(spans) > 1:
        return _result(
            success=False,
            error="section_ambiguous: multiple matching headings in "
            f"{field}. Read the field and give each subtree a unique heading.",
            **base,
        )
    trimmed = content.rstrip("\n")
    block = f"{'#' * heading_level} {section.strip()}\n\n{trimmed}\n"
    if spans:
        start, end = spans[0]
        if end < len(existing):
            block += "\n"
        elif not existing.endswith("\n"):
            block = block.rstrip("\n")
        updated = existing[:start] + block + existing[end:]
    else:
        separator = (
            ""
            if not existing or existing.endswith("\n\n")
            else ("\n" if existing.endswith("\n") else "\n\n")
        )
        updated = existing + separator + block
    result = execute_structured_write(
        item_id=item_id,
        field=field,
        content=updated,
        expected_content=existing,
        source=source or "",
        out=_NullSink(),
    )
    if not result.get("success"):
        error = str(result.get("error") or "structured write failed")
        return _result(success=False, error=error, **base)
    return _result(
        success=True,
        changed=bool(result.get("changed")),
        new_line_count=_line_count(updated),
        verification="ok",
        warning=str(result.get("sync_warning") or ""),
        **base,
    )
