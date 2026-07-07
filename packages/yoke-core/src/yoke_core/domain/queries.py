"""Filtered item-query and standard analysis surfaces.

This module owns the Python domain logic for querying items with filters
and performing standard non-done/non-cancelled/non-frozen/non-blocked
analysis.

Frozen and blocked semantics: ``items.frozen`` and ``items.blocked`` are
boolean flags (INTEGER 0/1 in SQLite). ``NULL`` and ``0`` both mean "not
set"; ``1`` means set. Both follow the same compatibility adapter contract:
``(<col> IS NULL OR <col> = 0)`` for unset, ``<col> = 1`` for set. The two
flags are orthogonal — an item can be both frozen and blocked, or either,
or neither, and each is independent of lifecycle ``status``.

Note on naming: ``items.blocked`` (this column) and ``path_claims.state='blocked'``
are unrelated. The former is an item-level routing/display flag; the latter
is a coordination state on a single path-claim row. They share only the
word "blocked".

Shell callers delegate into these semantics through ``service_client.py`` and
``query-items.sh``. Compatibility tests keep those adapters aligned with this
module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .lifecycle import TERMINAL, is_valid_item_status

# Item flag predicates moved to the shipped yoke_contracts.item_flags tier
# (so the board render ships core-free); re-exported for queries' callers.
from yoke_contracts.item_flags import (  # noqa: F401
    _coerce_flag,
    is_blocked,
    is_frozen,
)

# ---------------------------------------------------------------------------
# Frozen / blocked boolean-flag semantics
# ---------------------------------------------------------------------------




def _sql_flag_filter(value: bool, col: str) -> str:
    if value:
        return f"{col} = 1"
    return f"({col} IS NULL OR {col} = 0)"


def sql_frozen_filter(frozen: bool, col: str = "frozen") -> str:
    """Return a SQL condition fragment for filtering by frozen status.

    Args:
        frozen: True to match frozen items, False to match non-frozen.
        col: The column name (default ``frozen``).

    Returns:
        SQL condition string (no leading AND/WHERE).

    Preserves the ``query-items.sh`` compatibility contract:
    - ``frozen=True``  -> ``frozen = 1``
    - ``frozen=False`` -> ``(frozen IS NULL OR frozen = 0)``
    """
    return _sql_flag_filter(frozen, col)


def sql_blocked_filter(blocked: bool, col: str = "blocked") -> str:
    """Return a SQL condition fragment for filtering by blocked-flag status.

    Mirrors :func:`sql_frozen_filter` for ``items.blocked``:
    - ``blocked=True``  -> ``blocked = 1``
    - ``blocked=False`` -> ``(blocked IS NULL OR blocked = 0)``
    """
    return _sql_flag_filter(blocked, col)


# ---------------------------------------------------------------------------
# Item filter model
# ---------------------------------------------------------------------------


@dataclass
class ItemFilter:
    """A declarative filter for item queries.

    All fields are optional. When set, they restrict the query results.
    When multiple filters are set, they are combined with AND.
    """

    status: Optional[str] = None
    priority: Optional[str] = None
    item_type: Optional[str] = None
    frozen: Optional[bool] = None
    blocked: Optional[bool] = None
    project: Optional[str] = None
    project_id: Optional[int] = None

    # Exclusion filters (items matching these are excluded)
    exclude_statuses: Optional[Sequence[str]] = None
    exclude_cancelled: bool = False
    exclude_done: bool = False
    exclude_frozen: bool = False
    exclude_blocked: bool = False


def build_where_clause(
    filt: ItemFilter,
    table_prefix: str = "",
) -> Tuple[str, List[Any]]:
    """Build a SQL WHERE clause from an ``ItemFilter``.

    Returns a tuple of ``(where_clause, params)`` where ``where_clause``
    starts with ``WHERE`` if any conditions exist, or is empty string
    if no conditions.

    The *table_prefix* is prepended to column names (e.g., ``"i."``).

    Uses parameterized queries (``%s`` placeholders) for all user-provided
    values to prevent SQL injection.
    """
    conditions: List[str] = []
    params: List[Any] = []
    pfx = table_prefix

    if filt.status is not None:
        # Comma-separated multi-status matches any of the listed values —
        # the single-value exact match used to make multi-status recipes
        # (`--status idea,refining-idea`) silently match zero rows (13012).
        statuses = [s.strip() for s in filt.status.split(",") if s.strip()]
        if len(statuses) > 1:
            placeholders = ", ".join(["%s"] * len(statuses))
            conditions.append(f"{pfx}status IN ({placeholders})")
            params.extend(statuses)
        else:
            conditions.append(f"{pfx}status = %s")
            params.append(statuses[0] if statuses else filt.status)

    if filt.priority is not None:
        conditions.append(f"{pfx}priority = %s")
        params.append(filt.priority)

    if filt.item_type is not None:
        conditions.append(f"{pfx}type = %s")
        params.append(filt.item_type)

    if filt.frozen is not None:
        conditions.append(sql_frozen_filter(filt.frozen, col=f"{pfx}frozen"))
        # sql_frozen_filter is a literal condition; no param needed

    if filt.blocked is not None:
        conditions.append(sql_blocked_filter(filt.blocked, col=f"{pfx}blocked"))

    if filt.project_id is not None:
        conditions.append(f"{pfx}project_id = %s")
        params.append(int(filt.project_id))
    elif filt.project is not None:
        conditions.append(
            f"{pfx}project_id = ("
            "SELECT id FROM projects "
            "WHERE slug = %s OR CAST(id AS TEXT) = %s)"
        )
        params.extend([filt.project, filt.project])

    # Exclusion filters
    if filt.exclude_statuses:
        placeholders = ", ".join("%s" for _ in filt.exclude_statuses)
        conditions.append(f"{pfx}status NOT IN ({placeholders})")
        params.extend(filt.exclude_statuses)

    if filt.exclude_cancelled:
        conditions.append(f"{pfx}status <> %s")
        params.append("cancelled")

    if filt.exclude_done:
        conditions.append(f"{pfx}status <> %s")
        params.append("done")

    if filt.exclude_frozen:
        conditions.append(sql_frozen_filter(False, col=f"{pfx}frozen"))

    if filt.exclude_blocked:
        conditions.append(sql_blocked_filter(False, col=f"{pfx}blocked"))

    if not conditions:
        return ("", [])

    return ("WHERE " + " AND ".join(conditions), params)


# ---------------------------------------------------------------------------
# Standard analysis queries (non-done/non-cancelled/non-frozen)
# ---------------------------------------------------------------------------


def active_queue_filter(
    project: Optional[str] = None,
) -> ItemFilter:
    """Return an ``ItemFilter`` for the standard "active queue" analysis.

    The active queue is: items that are NOT done, NOT cancelled, NOT
    frozen, and NOT blocked. This is the canonical set of items that
    represent the current workload for analysis and reporting.

    Optionally scoped by project.
    """
    return ItemFilter(
        project=project,
        exclude_done=True,
        exclude_cancelled=True,
        exclude_frozen=True,
        exclude_blocked=True,
    )


def pending_work_filter(
    project: Optional[str] = None,
) -> ItemFilter:
    """Return an ``ItemFilter`` for items that still need work.

    Pending work: NOT done, NOT cancelled, NOT frozen, NOT blocked, and NOT
    in a pre-release or terminal success state (implemented/done). This is
    a stricter filter than ``active_queue_filter`` that excludes usher-ready
    items too.
    """
    return ItemFilter(
        project=project,
        exclude_statuses=("done", "cancelled", "implemented"),
        exclude_frozen=True,
        exclude_blocked=True,
    )


# ---------------------------------------------------------------------------
# Item classification helpers
# ---------------------------------------------------------------------------


def classify_item_state(
    status: str,
    frozen: Any,
    blocked: Any = None,
) -> str:
    """Classify an item into a high-level state category.

    Returns one of: ``"done"``, ``"cancelled"``, ``"frozen"``, ``"blocked"``,
    ``"terminal_failure"``, ``"active_work"``, ``"pipeline"``.

    The blocked-flag check fires after frozen and after the done/cancelled
    terminals so that a done/cancelled/frozen item is never reported as
    blocked. ``status='blocked'`` is preserved as legacy drift detection
    only — after the migration cutover no row should hold that lifecycle
    status; the doctor health check ``HC-blocked-status-drift`` flags any
    that do.

    This is useful for quick categorization without full board projection.
    """
    if status == "done":
        return "done"
    if status == "cancelled":
        return "cancelled"
    if is_frozen(frozen) and status not in ("done", "cancelled"):
        return "frozen"
    if is_blocked(blocked) and status not in ("done", "cancelled"):
        return "blocked"
    if status in ("stopped", "failed"):
        return "terminal_failure"
    if status in (
        "implementing",
        "reviewing-implementation",
        "reviewed-implementation",
        "polishing-implementation",
        "implemented",
        "release",
        "blocked",
    ):
        return "active_work"
    # idea, planned, refined-idea, planning, refining-plan
    return "pipeline"


# Back-compat alias for callers that adopted the spec name.
compute_dispatch_status = classify_item_state
