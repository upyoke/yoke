"""BOARD.md path-claim and coordination-lease keycap rendering.

Sibling of :mod:`yoke_contracts.board.sections_sessions`. Owns the path-claim
and coordination-lease decoration logic for the existing Claims column:

* ``YOK-N 📁<total>`` — work_claim with same-item path_claim decoration.
* ``📁<total> (YOK-N)`` — orphan path_claim with parens shape.
* ``📁<total> (🔩 <process_key>)`` — process-anchored orphan via work_claim_id.
* ``🔒 <lease_key>`` — coordination lease, project-scoped.

Keeps :mod:`sections_sessions` lean: the wire-in layer fetches claims and
calls :func:`build_session_keycaps` for the final ordered, decorated target
list. ``_chunk_claims`` (in the parent module) wraps the layout to a
display-width budget.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import item_ref


PATH_GLYPH = "\U0001f4c1"   # 📁
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

    Three match branches (any one returns the row):

    1. Typed session-owned: ``owner_kind='session'`` AND
       ``owner_session_id = session_id``.
    2. Typed process-owned via a work_claim this session holds:
       ``owner_kind='process'`` AND ``owner_work_claim_id`` resolves
       to a ``work_claims`` row with ``session_id = session_id``.
    3. Pre-migration legacy fallback: ``owner_kind IS NULL`` AND the
       row's legacy ``session_id = session_id`` AND the legacy
       ``item_id`` is NULL (otherwise the row is item-owned and would
       roll up through :func:`_path_claims_for_items`).

    Rows: (claim_id, item_id, work_claim_id, released_at, cancelled_at,
    release_reason, cancel_reason, declared_count). Terminal rows
    (released OR cancelled) are filtered when ``active_only`` is True.
    """
    terminal_filter = (
        " AND pc.released_at IS NULL AND pc.cancelled_at IS NULL "
        if active_only else ""
    )
    return db.query_quiet(
        f"""
        SELECT pc.id, pc.item_id, pc.work_claim_id,
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
          )) OR
          (pc.owner_kind IS NULL AND pc.session_id = %s
             AND pc.item_id IS NULL)
        )
        {terminal_filter}
        ORDER BY pc.id ASC
        """,
        (session_id, session_id, session_id),
    )


def _path_claims_for_items(
    db: BoardDBLike,
    item_ids: List[int],
    *,
    active_only: bool,
) -> List[Tuple]:
    """Fetch typed item-owned path_claims for the given ``item_ids``.

    Normal ticket file ownership is the typed ``owner_kind='item'``
    (with the legacy ``item_id`` column kept populated for cutover
    compatibility). Active-session rendering rolls these in so the
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
        if active_only else ""
    )
    placeholders = ",".join("%s" for _ in item_ids)
    return db.query_quiet(
        f"""
        SELECT pc.id, pc.item_id, pc.work_claim_id,
               pc.released_at, pc.cancelled_at,
               pc.release_reason, pc.cancel_reason,
               (SELECT COUNT(*)
                FROM path_claim_targets pct
                WHERE pct.claim_id = pc.id) AS declared_count
        FROM path_claims pc
        WHERE (
          (pc.owner_kind = 'item' AND pc.owner_item_id IN ({placeholders})) OR
          (pc.owner_kind IS NULL AND pc.item_id IN ({placeholders}))
        )
        {terminal_filter}
        ORDER BY pc.id ASC
        """,
        tuple(list(item_ids) + list(item_ids)),
    )


def leases_for_session(
    db: BoardDBLike,
    session_id: str,
    *,
    active_only: bool,
) -> List[Tuple]:
    """Fetch coordination_leases for ``session_id``.

    Rows: (lease_id, lease_key, released_at, release_reason). Terminal
    leases are filtered when ``active_only`` is True.
    """
    terminal_filter = (
        " AND released_at IS NULL "
        if active_only else ""
    )
    return db.query_quiet(
        f"""
        SELECT id, lease_key, released_at, release_reason
        FROM coordination_leases
        WHERE session_id = %s
        {terminal_filter}
        ORDER BY id ASC
        """,
        (session_id,),
    )


def _process_anchor(db: BoardDBLike, work_claim_id: Optional[int]) -> Optional[str]:
    """Resolve a work_claim_id to its process_key, when present and process-kind."""
    if work_claim_id is None:
        return None
    row = db.query_quiet(
        "SELECT process_key FROM work_claims WHERE id = %s",
        (work_claim_id,),
    )
    if not row:
        return None
    first = row[0]
    process_key = first[0] if first else None
    if isinstance(process_key, str) and process_key:
        return process_key
    return None


def _roll_up_path_claims(
    rows: List[Tuple],
) -> Dict[Optional[int], Dict[str, object]]:
    """Sum declared-path counts per item_id, retaining terminal hints.

    Returns dict keyed by item_id (None for orphan-process anchors). Each
    entry has ``count`` (int), ``release_reason`` (str|None — the first
    terminal hint observed; None when any row is non-terminal), and
    ``work_claim_id`` (int|None — used to resolve the process anchor when
    item_id is None).
    """
    rolled: Dict[Optional[int], Dict[str, object]] = {}
    for row in rows:
        item_id = row[1]
        work_claim_id = row[2]
        released_at = row[3]
        cancelled_at = row[4]
        release_reason = row[5] or row[6]
        declared_count = row[7] or 0
        bucket = rolled.setdefault(
            item_id,
            {"count": 0, "release_reason": None, "work_claim_id": None,
             "any_active": False},
        )
        bucket["count"] = int(bucket["count"]) + int(declared_count)
        if released_at is None and cancelled_at is None:
            bucket["any_active"] = True
        if bucket["release_reason"] is None and release_reason:
            bucket["release_reason"] = release_reason
        if bucket["work_claim_id"] is None and work_claim_id is not None:
            bucket["work_claim_id"] = work_claim_id
    return rolled


def build_session_keycaps(
    db: BoardDBLike,
    session_id: str,
    work_claim_targets: List[Tuple[str, Optional[int], Optional[str]]],
    *,
    active_only: bool,
) -> List[str]:
    """Return ordered keycap strings for a session row.

    ``work_claim_targets`` is a list of ``(target_str, item_id, release_reason)``
    where ``target_str`` is the parent module's :func:`_render_claim_target`
    output and ``release_reason`` is the work_claim's release reason (None for
    active session rows). ``item_id`` is the int item id of the work_claim,
    used to detect co-held path_claims and apply the ``📁N`` decoration.

    Active-session rows decorate the same-item work_claim with ``📁<count>``;
    orphan path_claims and leases append after work_claim keycaps. Recently-
    closed rows append ``(release_reason)`` to each terminal entry.
    """
    path_rows = path_claims_for_session(
        db, session_id, active_only=active_only,
    )
    lease_rows = leases_for_session(
        db, session_id, active_only=active_only,
    )

    # Normal ticket file ownership lives on path_claims.item_id and is
    # independent of session attribution. Roll item-linked claims for the
    # session's active work-claim items in alongside the session-linked
    # rows so the Claims column reflects file authority even when the
    # path_claim row has session_id IS NULL. Deduplicate by claim id so a
    # row that is both session-linked and item-linked is counted once.
    work_item_ids_int: List[int] = sorted({
        int(item_id) for _, item_id, _ in work_claim_targets
        if item_id is not None
    })
    if active_only and work_item_ids_int:
        seen_ids = {row[0] for row in path_rows}
        item_rows = _path_claims_for_items(
            db, work_item_ids_int, active_only=active_only,
        )
        merged_rows = list(path_rows) + [
            row for row in item_rows if row[0] not in seen_ids
        ]
    else:
        merged_rows = list(path_rows)

    rolled = _roll_up_path_claims(merged_rows)

    work_item_ids = {item_id for _, item_id, _ in work_claim_targets}
    decorated_targets: List[str] = []
    for target_str, item_id, release_reason in work_claim_targets:
        bucket = rolled.get(item_id)
        cell = target_str
        if bucket and int(bucket["count"]) > 0:
            cell = f"{cell} {PATH_GLYPH}{int(bucket['count'])}"
        if release_reason:
            cell = f"{cell} ({release_reason})"
        decorated_targets.append(cell)

    # Orphan path_claims (no matching work_claim on the same item).
    orphan_items = sorted(
        (item_id for item_id in rolled if item_id not in work_item_ids),
        key=lambda v: (v is None, v if v is not None else 0),
    )
    for item_id in orphan_items:
        bucket = rolled[item_id]
        count = int(bucket["count"])
        if count == 0:
            continue
        if item_id is not None:
            try:
                ref = item_ref(db, int(item_id))
            except Exception:
                ref = f"YOK-{item_id}"
            cell = f"{PATH_GLYPH}{count} ({ref})"
        else:
            process_key = _process_anchor(db, bucket["work_claim_id"])
            if process_key:
                cell = f"{PATH_GLYPH}{count} ({PROCESS_GLYPH} {process_key})"
            else:
                cell = f"{PATH_GLYPH}{count}"
        reason = bucket["release_reason"]
        if reason and not bucket["any_active"]:
            cell = f"{cell} ({reason})"
        decorated_targets.append(cell)

    # Coordination leases — always separate keycaps, never decorate work_claims.
    for lease_row in lease_rows:
        lease_key = lease_row[1] or "?"
        released_at = lease_row[2]
        release_reason = lease_row[3]
        cell = f"{LEASE_GLYPH} {lease_key}"
        if released_at is not None and release_reason:
            cell = f"{cell} ({release_reason})"
        decorated_targets.append(cell)

    return decorated_targets


__all__ = [
    "LEASE_GLYPH",
    "PATH_GLYPH",
    "PROCESS_GLYPH",
    "build_session_keycaps",
    "leases_for_session",
    "path_claims_for_session",
]
