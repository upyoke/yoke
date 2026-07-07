"""Canonical board grouping and stats projection.

This module owns the Python domain logic for projecting items into board
display buckets and computing board statistics. Board ordering is sourced
from ``yoke_core.domain.lifecycle.BOARD_COLUMN_ORDER``.

Board color palette (cool-to-warm-to-green arc):
    idea(purple) planning(indigo) refined(blue) implementing(yellow)
    reviewing(orange) implemented(green-circle) release(green-square)
    done(green-heart) blocked(red)

Board bucket names renamed from legacy vocabulary to current vocabulary:
    ready -> refined, active -> implementing, validate -> reviewing, passed -> implemented

Status-to-bucket mapping rules (in priority order):
    done, cancelled         -> done
    frozen (flag=1)         -> frozen   (excluded from normal board display)
    blocked (flag=1)        -> blocked  (item-level routing/display flag)
    blocked status (legacy) -> blocked  (drift detection — post-cutover any row
                                          with status='blocked' is doctor-flagged)
    stopped, failed         -> blocked
    implemented + active-run -> release  (active-run upgrade)
    implemented             -> implemented  (pre-release success state)
    release                 -> release
    implementing            -> implementing  (in-flight work)
    reviewing-implementation, reviewed-implementation,
    polishing-implementation -> reviewing
    refined-idea, planned   -> refined  (pipeline bucket)
    refining-idea           -> planning
    planning, refining-plan -> planning (epic-workflow-type)
    idea                    -> idea  (backlog bucket)
    unknown                 -> unknown

Type-aware overrides (when ``item_type`` is provided):
    epic + refined-idea        -> planning (issue default: refined)
    epic + reviewing-implementation -> implementing (issue default: reviewing)

Note: ``items.blocked`` and ``path_claims.state='blocked'`` are unrelated
concepts that share the word; ``items.blocked`` is the item-level routing
flag set by ``/yoke block``, and the latter is a coordination state on a
single path-claim row.

The board operates in a project-scoped context, showing items filtered
by project with frontier/project state projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .lifecycle import BOARD_COLUMN_ORDER

# Status -> board-bucket vocabulary moved to the shipped yoke_contracts.board
# tier so the board render ships core-free; re-exported here for existing callers.
from yoke_contracts.board.status import (  # noqa: F401
    BLOCKED_BUCKET,
    FROZEN_BUCKET,
    UNKNOWN_BUCKET,
    _STATUS_TO_BUCKET,
    _TYPE_AWARE_OVERRIDES,
    status_to_board_bucket,
)

# ---------------------------------------------------------------------------
# Board column constants
# ---------------------------------------------------------------------------

# Re-export for convenience
BOARD_COLUMNS = BOARD_COLUMN_ORDER



# ---------------------------------------------------------------------------
# Board stats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardStats:
    """Summary statistics for the board.

    Matches the current API BoardStats model contract.
    """

    total: int
    done: int
    active: int
    remaining: int


@dataclass
class BoardProjection:
    """Complete board projection: items grouped by bucket with stats.

    This is the domain-layer representation that the API endpoint converts
    to its response model.
    """

    project: Optional[str] = None
    columns: Dict[str, List[Any]] = field(default_factory=dict)
    stats: BoardStats = field(
        default_factory=lambda: BoardStats(total=0, done=0, active=0, remaining=0)
    )

    @classmethod
    def empty(
        cls,
        project: Optional[str] = None,
    ) -> "BoardProjection":
        """Return an empty board projection."""
        return cls(
            project=project,
            columns={},
            stats=BoardStats(total=0, done=0, active=0, remaining=0),
        )


# ---------------------------------------------------------------------------
# Board projection logic
# ---------------------------------------------------------------------------


@dataclass
class ItemForBoard:
    """Minimal item data needed for board projection.

    The *item* field holds the original item object (dict or model) to be
    placed into columns; the other fields drive the bucket classification.
    """

    item: Any
    status: str
    frozen_value: Any = None
    blocked_value: Any = None
    has_active_run: bool = False
    item_type: Optional[str] = None


def project_board(
    items: Sequence[ItemForBoard],
    project: Optional[str] = None,
) -> BoardProjection:
    """Project a sequence of items into a board.

    Items are classified into buckets using ``status_to_board_bucket()``.
    Items in the "frozen" or "unknown" buckets are excluded from the
    standard board columns (they don't appear on the board display).

    Cancelled items are excluded entirely (they map to "done" bucket but
    the shell board excludes ``cancelled`` from the query).

    Stats follow the current API contract:
    - total: count of all non-cancelled items
    - done: count in "done" bucket
    - active: count in "implementing" bucket
    - remaining: total - done - active
    """
    columns: Dict[str, List[Any]] = {col: [] for col in BOARD_COLUMNS}

    done_count = 0
    active_count = 0
    total = 0

    for item_data in items:
        bucket = status_to_board_bucket(
            status=item_data.status,
            frozen_value=item_data.frozen_value,
            has_active_run=item_data.has_active_run,
            item_type=item_data.item_type,
            blocked_value=item_data.blocked_value,
        )

        # Skip frozen and unknown items from normal display.
        # Blocked items remain visible (project_board callers map them
        # through the blocked column).
        if bucket in (FROZEN_BUCKET, UNKNOWN_BUCKET):
            continue

        total += 1

        if bucket in columns:
            columns[bucket].append(item_data.item)

        if bucket == "done":
            done_count += 1
        elif bucket == "implementing":
            active_count += 1

    remaining = total - done_count - active_count

    return BoardProjection(
        project=project,
        columns=columns,
        stats=BoardStats(
            total=total,
            done=done_count,
            active=active_count,
            remaining=remaining,
        ),
    )
