"""Revalidate a frozen item's path claims before thaw restores authority.

Frozen owners are dormant at overlap checks, so live work may register
and activate on the same paths while the parked item keeps its claim
rows. Thaw must not return those rows as a live door lock on top of
that work. Conflicting non-terminal claims become ``blocked``; claim
identity and history stay. Unconflicted claims keep their prior state.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from yoke_core.domain.schema_common import _table_exists

_NON_TERMINAL_STATES = ("planned", "blocked", "active")
THAW_OVERLAP_BLOCKED_REASON = (
    "thaw-time overlap with live coordination; "
    "reconcile before restoring this claim"
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, index: int, name: str) -> Any:
    return row[name] if hasattr(row, "keys") else row[index]


def _claim_target_ids(conn: Any, claim_id: int) -> List[int]:
    return [
        int(_cell(row, 0, "target_id"))
        for row in conn.execute(
            f"SELECT target_id FROM path_claim_targets "
            f"WHERE claim_id = {_p(conn)}",
            (claim_id,),
        ).fetchall()
    ]


def _item_owned_claims(conn: Any, item_id: int) -> Sequence[Any]:
    placeholders = ",".join(_p(conn) for _ in _NON_TERMINAL_STATES)
    return conn.execute(
        f"SELECT id, integration_target FROM path_claims "
        f"WHERE owner_kind = 'item' AND owner_item_id = {_p(conn)} "
        f"AND state IN ({placeholders})",
        (int(item_id), *_NON_TERMINAL_STATES),
    ).fetchall()


def revalidate_item_path_claims_on_thaw(item_id: int) -> tuple[int, ...]:
    """Block item-owned claims that would conflict if freeze lifted.

    Returns the claim ids demoted to ``blocked``. No-ops when path-claim
    tables are absent or the item owns no non-terminal claims.
    """
    demoted: list[int] = []
    with db_helpers.connect() as conn:
        if not _table_exists(conn, "path_claims"):
            return ()
        for row in _item_owned_claims(conn, item_id):
            claim_id = int(_cell(row, 0, "id"))
            integration_target = str(_cell(row, 1, "integration_target"))
            target_ids = _claim_target_ids(conn, claim_id)
            if not target_ids:
                continue
            classification = classify_overlap(
                conn,
                target_ids=target_ids,
                integration_target=integration_target,
                exclude_claim_id=claim_id,
                phase="register",
                candidate_item_id=int(item_id),
            )
            if classification is OverlapClassification.NONE:
                continue
            conn.execute(
                f"UPDATE path_claims SET state = 'blocked', "
                f"blocked_reason = {_p(conn)} WHERE id = {_p(conn)}",
                (THAW_OVERLAP_BLOCKED_REASON, claim_id),
            )
            demoted.append(claim_id)
        if demoted:
            conn.commit()
    return tuple(demoted)


__all__ = [
    "THAW_OVERLAP_BLOCKED_REASON",
    "revalidate_item_path_claims_on_thaw",
]
