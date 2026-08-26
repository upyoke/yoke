"""BOARD.md Claims-column queries.

Sibling of :mod:`yoke_contracts.board.sections_sessions_extra_claims`,
which turns these rows into keycaps. This module owns the reads: which
path claims a session is attributable for, which path claims its items
own, and which shared-operation coordination claims it is holding — plus
the SQL that renders each coordination key, so the renderer never needs
the engine's key decoder.
"""

from __future__ import annotations

from typing import List, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.coordination_claim_keys import (
    COORDINATION_SCOPE_KEY,
    COORDINATION_TARGET_KINDS,
    TARGET_KIND_MIGRATION_SERIALIZATION,
    key_prefix_for_kind,
)

_COORDINATION_KINDS_SQL = ", ".join(
    f"'{kind}'" for kind in COORDINATION_TARGET_KINDS
)
#: Render each claim's operator key in SQL so the board never needs the
#: engine's decoder to show what a session is holding.
_COORDINATION_KEY_SQL = (
    "CASE cc.target_kind "
    + " ".join(
        f"WHEN '{kind}' THEN '{key_prefix_for_kind(kind)}' || "
        f"(cc.scope::jsonb ->> '{COORDINATION_SCOPE_KEY[kind]}')"
        for kind in COORDINATION_TARGET_KINDS
    )
    + " END"
)


PATH_GLYPH = "\U0001f4c1"  # 📁
LEASE_GLYPH = "\U0001f512"  # 🔒
PROCESS_GLYPH = "🔩"


def path_claims_for_session(
    db: BoardDBLike,
    session_id: str,
    *,
    active_only: bool,
) -> List[Tuple]:
    """Fetch orphan path_claims attributable to ``session_id``.

    Returns only true session-owned or process-owned-via-held-work-claim
    rows — item-owned claims an item owns are intentionally NOT returned
    here even when the session registered them; they roll into the
    work-claim file count via :func:`_path_claims_for_items`. The
    registering session is provenance, not authority.

    Two match branches (any one returns the row):

    1. Typed session-owned: ``owner_kind='session'`` AND
       ``owner_session_id = session_id``.
    2. Typed process-owned via a work_claim this session holds:
       ``owner_kind='process'`` AND ``owner_work_claim_id`` resolves
       to a ``work_claims`` row with ``session_id = session_id``.
    Item-owned claims are excluded here; they roll up through :func:`_path_claims_for_items`.

    Rows: (claim_id, item_id, work_claim_id, released_at, cancelled_at,
    release_reason, cancel_reason, declared_count). Terminal rows
    (released OR cancelled) are filtered when ``active_only`` is True.
    """
    terminal_filter = (
        " AND pc.released_at IS NULL AND pc.cancelled_at IS NULL "
        if active_only
        else ""
    )
    return db.query_quiet(
        f"""
        SELECT pc.id, pc.owner_item_id AS item_id,
               pc.owner_work_claim_id AS work_claim_id,
               pc.released_at, pc.cancelled_at,
               pc.release_reason, pc.cancel_reason,
               (SELECT COUNT(*)
                FROM path_claim_targets pct
                WHERE pct.claim_id = pc.id) AS declared_count
        FROM path_claims pc
        WHERE (
          (pc.owner_kind = 'session' AND pc.owner_session_id = %s) OR
          (pc.owner_kind = 'process' AND pc.owner_work_claim_id IN (
              SELECT id FROM work_claims WHERE session_id = %s
          ))
        )
        {terminal_filter}
        ORDER BY pc.id ASC
        """,
        (session_id, session_id),
    )


def _path_claims_for_items(
    db: BoardDBLike,
    item_ids: List[int],
    *,
    active_only: bool,
) -> List[Tuple]:
    """Fetch typed item-owned path_claims for the given ``item_ids``.

    Normal work-item file ownership is the typed ``owner_kind='item'``
    (with the typed ``owner_item_id`` column). Active-session rendering rolls these in so the
    Claims column reflects the same file authority everyone else
    sees, regardless of which session registered the claim.

    Row shape mirrors :func:`path_claims_for_session`. Terminal rows
    are filtered when ``active_only`` is True. Returns an empty list
    when ``item_ids`` is empty so callers do not need to guard the
    no-work-claim case before invoking.
    """
    if not item_ids:
        return []
    terminal_filter = (
        " AND pc.released_at IS NULL AND pc.cancelled_at IS NULL "
        if active_only
        else ""
    )
    placeholders = ",".join("%s" for _ in item_ids)
    return db.query_quiet(
        f"""
        SELECT pc.id, pc.owner_item_id AS item_id,
               pc.owner_work_claim_id AS work_claim_id,
               pc.released_at, pc.cancelled_at,
               pc.release_reason, pc.cancel_reason,
               (SELECT COUNT(*)
                FROM path_claim_targets pct
                WHERE pct.claim_id = pc.id) AS declared_count
        FROM path_claims pc
        WHERE (
          (pc.owner_kind = 'item' AND pc.owner_item_id IN ({placeholders}))
        )
        {terminal_filter}
        ORDER BY pc.id ASC
        """,
        tuple(item_ids),
    )


def coordination_claims_for_session(
    db: BoardDBLike,
    session_id: str,
    *,
    active_only: bool,
) -> List[Tuple]:
    """Fetch shared-operation coordination claims for ``session_id``.

    Rows: (claim_id, key, released_at, release_reason, target_kind,
    owner_item_id). A session sees the claims it holds plus the
    migration territory owned by any item it currently claims, because
    that hold outlives the session and still belongs on its row.
    Terminal claims are filtered when ``active_only`` is True.
    """
    terminal_filter = " AND cc.released_at IS NULL " if active_only else ""
    typed_sql = f"""
        SELECT cc.id, {_COORDINATION_KEY_SQL}, cc.released_at,
               cc.release_reason, cc.target_kind,
               CAST(cc.scope::jsonb ->> 'item_id' AS INTEGER)
        FROM work_claims cc
        WHERE cc.target_kind IN ({_COORDINATION_KINDS_SQL})
        AND (
          cc.session_id = %s
          OR (cc.target_kind = '{TARGET_KIND_MIGRATION_SERIALIZATION}'
              AND CAST(cc.scope::jsonb ->> 'item_id' AS INTEGER) IN (
              SELECT CAST(wc.scope::jsonb ->> 'item_id' AS INTEGER)
              FROM work_claims wc
              WHERE wc.session_id = %s AND wc.target_kind = 'item'
          ))
        )
        {terminal_filter}
        ORDER BY cc.id DESC
        """
    return db.query_quiet(typed_sql, (session_id, session_id))



__all__ = [
    "coordination_claims_for_session",
    "path_claims_for_session",
]
