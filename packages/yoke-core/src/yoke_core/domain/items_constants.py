"""Constants and pure helpers shared across ``items`` query/write modules.

This module owns the derived column sets and small pure helpers used by
both :mod:`yoke_core.domain.items_queries` and
:mod:`yoke_core.domain.items_writes`, and re-exports the base vocabulary
that :mod:`yoke_contracts.items_projection` defines. The public façade
:mod:`yoke_core.domain.items` re-exports the names listed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Canonical column order for pipe-delimited row output ("body" is a
# virtual field rendered on demand) and the structured-field set. Both are
# defined in yoke_contracts because the CLI renders them in
# `yoke items get --help` and cannot import the engine; re-exported here so
# engine callers keep this import site.
from yoke_contracts.items_projection import (
    CANONICAL_COLUMNS,
    STRUCTURED_FIELDS,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ITEM_ACTOR_ID = "2"

# DB-only columns (body excluded — it's virtual).
_DB_COLUMNS = tuple(c for c in CANONICAL_COLUMNS if c != "body")

# Columns used in the shorter ``list`` output (16 columns).
LIST_COLUMNS = (
    "id",
    "title",
    "workflow_id",
    "workflow_version_id",
    "status",
    "priority",
    "frozen",
    "github_issue",
    "deployed_to",
    "body",
    "merged_at",
    "created_at",
    "updated_at",
)

# Fields that contain large text and need file-based read/write paths.
# "body" is virtual and included so validators recognize the public field.
LARGE_TEXT_FIELDS = STRUCTURED_FIELDS | {"body"}

# Content-bearing structured fields that track spec_updated_at/by.
# db_mutation_profile / db_compatibility_attestation ARE content-bearing: each
# declares or argues about a governed DB mutation and is part of the item's
# editable spec surface.
CONTENT_FIELDS = frozenset(
    {
        "spec",
        "design_spec",
        "technical_plan",
        "worktree_plan",
        "db_mutation_profile",
        "db_compatibility_attestation",
    }
)

# Integer fields (no quoting needed in raw SQL — but we use parameterised
# queries everywhere, so this is mainly for the frozen / blocked bool mapping).
INTEGER_FIELDS = frozenset(
    {
        "frozen",
        "blocked",
        "id",
        "project_id",
        "project_sequence",
        "workflow_version_id",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coalesce(value: Any, default: str = "") -> str:
    """Coalesce None to *default*."""
    if value is None:
        return default
    return str(value)


def _map_frozen_read(value: Any) -> str:
    """Map frozen integer to boolean string for reads."""
    if value == 1 or value == "1":
        return "true"
    if value == 0 or value == "0":
        return "false"
    return ""


def _map_frozen_write(value: str) -> Optional[int]:
    """Map frozen boolean string to integer for writes."""
    if value in ("true", "1"):
        return 1
    if value in ("false", "0"):
        return 0
    if value in ("", "null"):
        return None
    return int(value)


def _map_blocked_read(value: Any) -> str:
    """Map blocked integer to boolean string for reads.

    Same shape as :func:`_map_frozen_read` — the two are independent flags
    on the items table; see ``yoke_core.domain.queries`` for the full
    orthogonality contract.
    """
    return _map_frozen_read(value)


def _map_blocked_write(value: str) -> Optional[int]:
    """Map blocked boolean string to integer for writes.

    Same shape as :func:`_map_frozen_write`.
    """
    return _map_frozen_write(value)


def _to_val(s: str, is_int: bool = False) -> Any:
    """Map empty or 'null' to None; parse integers for int fields."""
    if s == "" or s == "null":
        return None
    if is_int:
        try:
            return int(s)
        except (ValueError, TypeError):
            return None
    return s


def _pipe_row(row) -> str:
    """Format a sqlite3.Row as a pipe-delimited string."""
    return "|".join(_coalesce(v) for v in row)
