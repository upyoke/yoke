"""BOARD.md Claims-column queries.

Sibling of :mod:`yoke_contracts.board.sections_sessions_extra_claims`,
which turns these rows into keycaps. This module owns the reads: which
path claims a session is attributable for, which path claims its items
own, and which shared-operation coordination claims it is holding — plus
the SQL that renders each coordination key, so the renderer never needs
the engine's key decoder.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_sessions_occupancy import occupancy_docs_by_project
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
    params = (session_id, session_id)
    # Replay coverage: a payload recorded before this read existed has no
    # entry for it, and the board must render without coordination keycaps
    # rather than fail the whole rebuild.
    probe = getattr(db, "has_query_quiet", None)
    if callable(probe) and not probe(typed_sql, params):
        return []
    return db.query_quiet(typed_sql, params)



def strategy_docs_by_project_for_session(
    db: BoardDBLike,
    session_id: str,
    *,
    active_only: bool,
) -> Dict[int, List[str]]:
    """Session-owned strategy-document slugs, keyed by the project each steers.

    The steering line pairs every steered project with its own documents,
    so the project has to survive the read — two projects steering from
    same-named documents are otherwise indistinguishable. Missing table or
    an unrecorded replay query yields an empty mapping so a board payload
    from before this read still renders.
    """
    if active_only:
        cached = occupancy_docs_by_project(db, session_id)
        if cached:
            return cached
    terminal_filter = " AND sdc.released_at IS NULL" if active_only else ""
    sql = f"""
        SELECT sdc.project_id, sdc.strategy_doc_slug
        FROM strategy_doc_claims sdc
        WHERE sdc.owner_kind = 'session'
          AND sdc.owner_session_id = %s
          {terminal_filter}
        ORDER BY sdc.project_id, sdc.strategy_doc_slug
        """
    params = (session_id,)
    probe = getattr(db, "has_query_quiet", None)
    if callable(probe) and not probe(sql, params):
        return {}
    by_project: Dict[int, List[str]] = {}
    for row in db.query_quiet(sql, params):
        if not row or row[1] is None or row[0] is None:
            continue
        by_project.setdefault(int(row[0]), []).append(str(row[1]))
    return by_project


__all__ = [
    "coordination_claims_for_session",
    "path_claims_for_session",
    "strategy_docs_by_project_for_session",
]
