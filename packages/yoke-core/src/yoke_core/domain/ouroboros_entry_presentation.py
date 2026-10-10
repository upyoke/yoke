"""Canonical learning-log cells, pipe rows and correction-link projections."""

from typing import Optional

from yoke_contracts.timestamps import format_instant


def entry_wire_value(name, value):
    if name == "id":
        return int(value)
    if name in ("timestamp", "reviewed_at", "archived_at"):
        return format_instant(value) if value is not None else None
    return "" if value is None else str(value)


def _format_row(row) -> str:
    # Normalize newlines here; SQLite char(10) is not portable PostgreSQL SQL.
    return "|".join(
        "" if value is None else str(value).replace("\n", " ") for value in tuple(row)
    )


def _apply_correction_link(entry: dict, link: Optional[dict]) -> None:
    """Project both supersede directions onto an entry, absent as None."""
    entry["corrects"] = (link or {}).get("corrects")
    entry["superseded_by"] = (link or {}).get("superseded_by")
