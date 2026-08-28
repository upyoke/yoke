"""BOARD.md path-claim and coordination-claim keycap rendering.

Sibling of :mod:`yoke_contracts.board.sections_sessions`. Owns the path-claim
and coordination-claim decoration logic for the existing Claims column:

* ``PREFIX-N 📁<total>`` — work_claim with same-item path_claim decoration.
* ``📁<total> (PREFIX-N)`` — orphan path_claim with parens shape.
* ``📁<total> (🔩 <process_key>)`` — process-anchored orphan via the owning
  work claim.
* ``🔒 <key>`` — shared-operation coordination claim.
* ``🛞 steering <slug>·<DOC>; <slug>·<DOC>`` — everything this session
  steers, on one entry.

Keeps :mod:`sections_sessions` lean: the wire-in layer fetches claims and
calls :func:`build_session_keycaps` for the final ordered, decorated target
list. An item keycap carries its own ``workflow·stage``, because the
session-level status beside it describes only one of the items a session
holds. ``_chunk_claims`` (in the parent module) wraps the layout to a
display-width budget.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import item_ref
from yoke_contracts.board.sections_sessions_layout import _dedup_lease_rows
from yoke_contracts.board.sections_sessions_claim_reads import (
    _path_claims_for_items,
    coordination_claims_for_session,
    path_claims_for_session,
    strategy_docs_by_project_for_session,
)
from yoke_contracts.board.sections_sessions_occupancy import occupancy_project_slug
from yoke_contracts.coordination_claim_keys import (
    TARGET_KIND_MIGRATION_SERIALIZATION,
)
from yoke_contracts.item_ref import format_item_ref
from yoke_contracts.merge_queue_status import render_merge_queue_status


PATH_GLYPH = "\U0001f4c1"  # 📁
LEASE_GLYPH = "\U0001f512"  # 🔒
PROCESS_GLYPH = "🔩"
STEERING_GLYPH = "🛞"


def _item_lifecycle(db: BoardDBLike, item_ids: List[int]) -> Dict[int, str]:
    """Return ``workflow·stage`` per claimed item, read in one query.

    An item claim that shows only its ref leaves an operator unable to say
    how far along the work is or which lifecycle its stage names belong to,
    and the session-level status field beside it describes only one claim.
    """
    if not item_ids:
        return {}
    sql = (
        "SELECT id, workflow_id, status FROM items WHERE id IN ("
        + ",".join("%s" for _ in item_ids)
        + ")"
    )
    params = tuple(item_ids)
    probe = getattr(db, "has_query_quiet", None)
    if callable(probe) and not probe(sql, params):
        return {}
    labels: Dict[int, str] = {}
    for row in db.query_quiet(sql, params):
        if not row or row[0] is None or not row[2]:
            continue
        labels[int(row[0])] = f"{row[1]}·{row[2]}" if row[1] else str(row[2])
    return labels


def _steering_keycap(
    db: BoardDBLike,
    project_ids: List[int],
    docs_by_project: Dict[int, List[str]],
) -> str:
    """One entry naming every project steered and the documents behind each.

    Semicolons separate projects and commas separate one project's
    documents, so two projects steering from same-named documents still
    read as two holds.
    """
    entries: List[str] = []
    for project_id in project_ids:
        slug = occupancy_project_slug(db, project_id) or str(project_id)
        docs = docs_by_project.get(project_id) or []
        entries.append(f"{slug}·{', '.join(docs)}" if docs else slug)
    return f"{STEERING_GLYPH} steering {'; '.join(entries)}"


def _merge_queue_status(db: BoardDBLike, item_id: int) -> str:
    sql = (
        "SELECT status, merge_queue_enqueued_at, merge_queue_landed_at "
        "FROM items WHERE id = %s"
    )
    has_query_quiet = getattr(db, "has_query_quiet", None)
    if callable(has_query_quiet) and not has_query_quiet(sql, (item_id,)):
        return ""
    rows = db.query_quiet(sql, (item_id,))
    if not rows:
        return ""
    return render_merge_queue_status(rows[0][1], rows[0][2], item_status=rows[0][0])


def _process_anchor(db: BoardDBLike, work_claim_id: Optional[int]) -> Optional[str]:
    """Resolve a work-claim id to its process key, when process-kind."""
    if work_claim_id is None:
        return None
    row = db.query_quiet(
        "SELECT scope FROM work_claims WHERE id = %s AND target_kind = 'process'",
        (work_claim_id,),
    )
    if not row:
        return None
    raw_scope = row[0][0] if row[0] else None
    try:
        scope = raw_scope if isinstance(raw_scope, dict) else json.loads(raw_scope)
    except (TypeError, ValueError):
        return None
    process_key = scope.get("process_key") if isinstance(scope, dict) else None
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
            {
                "count": 0,
                "release_reason": None,
                "work_claim_id": None,
                "any_active": False,
            },
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
    steering_project_ids: Optional[List[int]] = None,
) -> List[str]:
    """Return ordered keycap strings for a session row.

    ``work_claim_targets`` is a list of ``(target_str, item_id, release_reason)``
    where ``target_str`` is the parent module's :func:`_render_claim_target`
    output and ``release_reason`` is retained for call-site compatibility
    (ignored for rendering). ``item_id`` is the int item id of the work_claim,
    used to detect co-held path_claims and apply the ``📁N`` decoration.

    Active-session rows decorate the same-item work_claim with ``📁<count>``;
    orphan path_claims and leases append after work_claim keycaps. Repeated
    leases on the same ``lease_key`` collapse to the most recent row (same
    pattern as work-claim target dedup). Release reasons are not rendered —
    Claims stays occupancy-shaped, not an audit log.
    """
    path_rows = path_claims_for_session(
        db,
        session_id,
        active_only=active_only,
    )
    lease_rows = _dedup_lease_rows(
        coordination_claims_for_session(db, session_id, active_only=active_only),
    )

    # Normal work-item file ownership lives on path_claims.owner_item_id and is
    # independent of session attribution. Roll item-linked claims for the
    # session's active work-claim items in alongside the session-linked
    # rows so the Claims column reflects file authority even when the
    # path claim has no session owner. Deduplicate by claim id so a
    # row that is both session-linked and item-linked is counted once.
    work_item_ids_int: List[int] = sorted(
        {int(item_id) for _, item_id, _ in work_claim_targets if item_id is not None}
    )
    if active_only and work_item_ids_int:
        seen_ids = {row[0] for row in path_rows}
        item_rows = _path_claims_for_items(
            db,
            work_item_ids_int,
            active_only=active_only,
        )
        merged_rows = list(path_rows) + [
            row for row in item_rows if row[0] not in seen_ids
        ]
    else:
        merged_rows = list(path_rows)

    rolled = _roll_up_path_claims(merged_rows)

    work_item_ids = {item_id for _, item_id, _ in work_claim_targets}
    lifecycle = _item_lifecycle(db, work_item_ids_int)
    decorated_targets: List[str] = []
    for target_str, item_id, _release_reason in work_claim_targets:
        bucket = rolled.get(item_id)
        cell = target_str
        if item_id is not None and lifecycle.get(int(item_id)):
            cell = f"{cell} {lifecycle[int(item_id)]}"
        if bucket and int(bucket["count"]) > 0:
            cell = f"{cell} {PATH_GLYPH}{int(bucket['count'])}"
        if item_id is not None:
            queue_status = _merge_queue_status(db, int(item_id))
            if queue_status:
                cell = f"{cell} · {queue_status}"
        decorated_targets.append(cell)

    # Steering is one fact however many projects it covers: one entry, not a
    # lock row per project plus a separate document row.
    docs_by_project = strategy_docs_by_project_for_session(
        db,
        session_id,
        active_only=active_only,
    )
    steered = list(steering_project_ids or [])
    if steered or docs_by_project:
        for project_id in sorted(docs_by_project):
            if project_id not in steered:
                steered.append(project_id)
        decorated_targets.append(_steering_keycap(db, steered, docs_by_project))

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
                ref = format_item_ref(None, None, None, item_id=int(item_id))
            cell = f"{PATH_GLYPH}{count} ({ref})"
        else:
            process_key = _process_anchor(db, bucket["work_claim_id"])
            if process_key:
                cell = f"{PATH_GLYPH}{count} ({PROCESS_GLYPH} {process_key})"
            else:
                cell = f"{PATH_GLYPH}{count}"
        decorated_targets.append(cell)

    # Coordination claims — always separate keycaps, never decorate work_claims.
    for lease_row in lease_rows:
        lease_key = lease_row[1] or "?"
        target_kind = lease_row[4] if len(lease_row) > 4 else None
        owner_item_id = lease_row[5] if len(lease_row) > 5 else None
        if (
            target_kind == TARGET_KIND_MIGRATION_SERIALIZATION
            and owner_item_id is not None
        ):
            try:
                ref = item_ref(db, int(owner_item_id))
            except Exception:
                ref = format_item_ref(None, None, None, item_id=int(owner_item_id))
            decorated_targets.append(f"{LEASE_GLYPH} {lease_key} ({ref})")
        else:
            decorated_targets.append(f"{LEASE_GLYPH} {lease_key}")
    return decorated_targets


__all__ = [
    "LEASE_GLYPH",
    "PATH_GLYPH",
    "PROCESS_GLYPH",
    "STEERING_GLYPH",
    "build_session_keycaps",
    "path_claims_for_session",
]
