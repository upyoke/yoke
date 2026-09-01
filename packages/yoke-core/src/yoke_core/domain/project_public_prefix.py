"""Public item prefix is an explicit, universe-unique project setting."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import query_rows


REQUIRED_PREFIX_RECOVERY = (
    "Pass --public-item-prefix PREFIX on `yoke projects create`, or set the "
    "public_item_prefix field on the create form / wizard project step."
)
DUPLICATE_PREFIX_RECOVERY = (
    "Choose a different prefix. List existing prefixes with `yoke projects list`."
)


def require_public_item_prefix(value: Optional[str]) -> str:
    """Return a stripped prefix, or refuse with the create-path recovery."""
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(
            "public_item_prefix is required. " + REQUIRED_PREFIX_RECOVERY
        )
    return cleaned


def assert_prefix_available(
    conn: Any,
    prefix: str,
    *,
    excluding_project_id: Optional[int] = None,
) -> None:
    """Refuse a prefix already used by another project (case-insensitive)."""
    rows = query_rows(
        conn,
        "SELECT id, slug FROM projects "
        "WHERE LOWER(public_item_prefix) = LOWER(%s)",
        (prefix,),
    )
    for row in rows:
        holder_id = int(row["id"])
        if excluding_project_id is not None and holder_id == excluding_project_id:
            continue
        raise ValueError(
            f"public_item_prefix {prefix!r} is already used by project "
            f"{row['slug']!r} (id {holder_id}). {DUPLICATE_PREFIX_RECOVERY}"
        )


def typed_project_field(name: str, value: Any) -> Any:
    """Keep ``id`` numeric on every project surface that projects a row."""
    if value is None or value == "":
        return None
    if name == "id":
        return int(value)
    return value


__all__ = [
    "DUPLICATE_PREFIX_RECOVERY",
    "REQUIRED_PREFIX_RECOVERY",
    "assert_prefix_available",
    "require_public_item_prefix",
    "typed_project_field",
]
