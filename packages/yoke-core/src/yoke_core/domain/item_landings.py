"""Reading and appending an item's landing history.

One row per landing, never updated and never replaced. The schema and the
reasoning behind the row's key live in
:mod:`yoke_core.domain.item_landings_schema`.

Appending is idempotent on ``(item_id, merge_sha)`` because close-out is
re-entrant: a merge whose waiting process died is resumed by re-running the
same command, and it converges on the landing it already recorded rather than
recording it a second time. Only a landing with a *different* merge identity
is a second landing.

Order is by ``id``, oldest first, which is how the item page lists them and
what makes "the newest landing" a single answer even when two landings share
a timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.session_message_types import row_dict

#: Columns in the order every read and write below names them.
_COLUMNS = (
    "id",
    "item_id",
    "merge_sha",
    "candidate_sha",
    "pr_number",
    "target_branch",
    "route",
    "landed_at",
)


@dataclass(frozen=True)
class ItemLanding:
    """One landing an item made on its base branch."""

    item_id: int
    merge_sha: str
    route: str
    landed_at: str
    candidate_sha: str = ""
    pr_number: str = ""
    target_branch: str = ""
    #: Assigned by the database on append; zero on a row not yet written.
    id: int = 0

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "merge_sha": self.merge_sha,
            "candidate_sha": self.candidate_sha,
            "pr_number": self.pr_number,
            "target_branch": self.target_branch,
            "route": self.route,
            "landed_at": self.landed_at,
        }


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _from_row(value: dict[str, Any]) -> ItemLanding:
    return ItemLanding(
        id=int(value["id"]),
        item_id=int(value["item_id"]),
        merge_sha=str(value["merge_sha"]),
        candidate_sha=str(value.get("candidate_sha") or ""),
        pr_number=str(value.get("pr_number") or ""),
        target_branch=str(value.get("target_branch") or ""),
        route=str(value["route"]),
        landed_at=str(value.get("landed_at") or ""),
    )


def append_landing(conn: Any, landing: ItemLanding) -> bool:
    """Record ``landing``. Returns whether this call wrote a new row.

    A ``False`` return is the re-entered close-out converging on the landing
    it already recorded, not a failure: the row is there either way.
    """
    p = _p(conn)
    cursor = conn.execute(
        "INSERT INTO item_landings "
        "(item_id,merge_sha,candidate_sha,pr_number,target_branch,route,"
        "landed_at) "
        f"VALUES ({','.join([p] * 7)}) "
        "ON CONFLICT(item_id, merge_sha) DO NOTHING",
        (
            int(landing.item_id),
            landing.merge_sha,
            landing.candidate_sha,
            landing.pr_number,
            landing.target_branch,
            landing.route,
            landing.landed_at,
        ),
    )
    return bool(cursor.rowcount)


def landings_for_item(conn: Any, item_id: int) -> tuple[ItemLanding, ...]:
    """Every landing this item has made, oldest first."""
    p = _p(conn)
    rows = conn.execute(
        f"SELECT {','.join(_COLUMNS)} FROM item_landings "
        f"WHERE item_id={p} ORDER BY id",
        (int(item_id),),
    ).fetchall()
    return tuple(_from_row(row_dict(row)) for row in rows)


def landing_counts(conn: Any, item_ids: Iterable[int]) -> dict[int, int]:
    """How many landings each of ``item_ids`` has made.

    Items with no landing are absent rather than zero, so a caller can tell
    "never landed" from "landed once" without a second read.
    """
    ids = [int(item_id) for item_id in item_ids]
    if not ids:
        return {}
    p = _p(conn)
    placeholders = ",".join(p for _ in ids)
    rows = conn.execute(
        "SELECT item_id, COUNT(*) AS landings FROM item_landings "
        f"WHERE item_id IN ({placeholders}) GROUP BY item_id",
        tuple(ids),
    ).fetchall()
    counts: dict[int, int] = {}
    for row in rows:
        value = row_dict(row)
        counts[int(value["item_id"])] = int(value["landings"])
    return counts


__all__ = [
    "ItemLanding",
    "append_landing",
    "landing_counts",
    "landings_for_item",
]
