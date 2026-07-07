"""Markdown rendering for taught product-boundary recipe drift."""

from __future__ import annotations

from typing import Iterable

from yoke_cli.product_boundary_teaching import MissingTeaching, TaughtSurface, TeachingAudit


_MAX_TEACHING_DRIFT_ROWS_PER_CLASS = 50
_MAX_MISSING_TEACHING_ROWS = 100


def render_teaching_audit_markdown(audit: TeachingAudit) -> list[str]:
    surfaces = audit.surfaces
    drift_surfaces = [row for row in surfaces if row.drift_type]
    drift_by_type: dict[str, int] = {}
    for row in drift_surfaces:
        assert row.drift_type is not None
        drift_by_type[row.drift_type] = drift_by_type.get(row.drift_type, 0) + 1
    for row in audit.missing:
        drift_by_type[row.drift_type] = drift_by_type.get(row.drift_type, 0) + 1
    lines = [
        "## taught-recipe surface audit",
        "",
        "Inventories command-looking recipes from generated packets, Yoke skills, "
        "and live docs; compares them to the live `yoke` registry plus "
        "permanent/tool-shaped operation inventory.",
        "",
        f"- Taught surfaces inventoried: **{len(surfaces)}**",
        f"- Drift rows: **{audit.drift_count}**",
    ]
    if drift_by_type:
        lines.append(
            "- Drift classes: "
            + ", ".join(f"{name}={count}" for name, count in sorted(drift_by_type.items()))
        )
    else:
        lines.append("- Drift classes: none")
    lines.append("")
    lines.extend(_render_drift_surfaces(drift_surfaces))
    lines.extend(_render_missing(audit.missing))
    return lines


def _render_drift_surfaces(rows: list[TaughtSurface]) -> list[str]:
    if not rows:
        return []
    lines = [
        "### taught surface drift",
        "",
        "| drift_type | command | resolution | source | line | smoke/error |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    shown_count = 0
    for row in _capped_drift_surfaces(rows):
        if row is None:
            lines.append(
                "| _omitted_ | additional rows in this drift class |  |  |  | see counts above |"
            )
            continue
        shown_count += 1
        values = (
            row.drift_type or "",
            row.recipe,
            row.resolution,
            row.source,
            str(row.line_number),
            row.smoke_error or "",
        )
        lines.append("| " + " | ".join(_md(value) for value in values) + " |")
    if shown_count < len(rows):
        lines.append(
            f"| _summary_ | rendered {shown_count} of {len(rows)} taught-surface drift rows |  |  |  | full rows available from `generate_teaching_audit()` |"
        )
    lines.append("")
    return lines


def _render_missing(rows: tuple[MissingTeaching, ...]) -> list[str]:
    if not rows:
        return []
    lines = [
        "### live commands missing from teaching",
        "",
        "| drift_type | command | source_kind | function_id |",
        "| --- | --- | --- | --- |",
    ]
    missing_rows = sorted(rows, key=_missing_sort_key)
    for row in missing_rows[:_MAX_MISSING_TEACHING_ROWS]:
        values = (row.drift_type, row.command_form, row.source_kind, row.function_id or "")
        lines.append("| " + " | ".join(_md(value) for value in values) + " |")
    if len(missing_rows) > _MAX_MISSING_TEACHING_ROWS:
        lines.append(
            f"| _summary_ | rendered {_MAX_MISSING_TEACHING_ROWS} of {len(missing_rows)} missing-teaching rows |  | full rows available from `generate_teaching_audit()` |"
        )
    lines.append("")
    return lines


def _missing_sort_key(row: MissingTeaching) -> tuple[str, str, str]:
    return (row.drift_type, row.source_kind, row.command_form)


def _capped_drift_surfaces(rows: Iterable[TaughtSurface]):
    current_type = None
    count_for_type = 0
    omitted_for_type = False
    for row in sorted(
        rows,
        key=lambda r: (r.drift_type or "", r.command_form, r.source, r.line_number),
    ):
        if row.drift_type != current_type:
            if omitted_for_type:
                yield None
            current_type = row.drift_type
            count_for_type = 0
            omitted_for_type = False
        count_for_type += 1
        if count_for_type <= _MAX_TEACHING_DRIFT_ROWS_PER_CLASS:
            yield row
        else:
            omitted_for_type = True
    if omitted_for_type:
        yield None


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


__all__ = ["render_teaching_audit_markdown"]
