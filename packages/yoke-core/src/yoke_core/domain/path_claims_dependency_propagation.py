"""Re-classify downstream blocked claims after release/status changes."""

from __future__ import annotations

import os
from typing import Any, List, Optional, Set

from yoke_core.domain import db_backend


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _claim_owning_item(conn: Any, claim_id: int):
    p = _p(conn)
    row = conn.execute(
        f"SELECT item_id FROM path_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _strip_sun(text: str) -> str:
    text = str(text or "").strip()
    if text[:4].lower() == "yok-":
        text = text[4:]
    return text.lstrip("0") or "0"


def _item_status(conn: Any, item_id: int) -> str:
    p = _p(conn)
    row = conn.execute(
        f"SELECT status FROM items WHERE id = {p}", (item_id,),
    ).fetchone()
    return str(row[0]) if row and row[0] else ""


def _direct_downstream_claims(
    conn: Any, released_claim_id: int,
) -> List[int]:
    """Return blocked claims that directly named ``released_claim_id``."""
    rows = conn.execute(
        "SELECT id, blocked_reason FROM path_claims WHERE state = 'blocked'",
    ).fetchall()
    return [
        int(r[0]) for r in rows
        if _blocked_reason_claim_id(str(r[1] or "")) == released_claim_id
    ]


def _blocked_reason_claim_id(blocked_reason: str) -> int | None:
    marker = "path_claims.id="
    if marker not in blocked_reason:
        return None
    tail = blocked_reason.rsplit(marker, 1)[1].strip()
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None


def _dep_satisfied_downstream_claims(
    conn: Any, released_claim_id: int,
) -> List[int]:
    """Return blocked claims whose dep edge is now satisfied."""
    blocking_item_id = _claim_owning_item(conn, released_claim_id)
    if blocking_item_id is None:
        return []
    blocking_status = _item_status(conn, blocking_item_id)
    try:
        edges = conn.execute(
            "SELECT dependent_item, blocking_item, satisfaction "
            "FROM item_dependencies"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    satisfied_dependent_items: Set[int] = set()
    for raw_dep, raw_blk, sat in edges:
        if _strip_sun(raw_blk) != str(blocking_item_id):
            continue
        sat_text = str(sat or "status:done").strip()
        if sat_text.startswith("status:"):
            wanted = sat_text.split(":", 1)[1].strip()
            if blocking_status == wanted:
                try:
                    satisfied_dependent_items.add(int(_strip_sun(raw_dep)))
                except ValueError:
                    continue

    if not satisfied_dependent_items:
        return []
    p = _p(conn)
    placeholders = ",".join(p for _ in satisfied_dependent_items)
    rows = conn.execute(
        f"SELECT id FROM path_claims "
        f"WHERE state = 'blocked' AND item_id IN ({placeholders})",
        tuple(int(i) for i in satisfied_dependent_items),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _select_surviving_upstream(
    conn: Any, *, downstream_claim_id: int,
    integration_target: str, serial_only: bool = False,
) -> Optional[int]:
    """Pick a surviving overlap, optionally restricted to forward serial."""
    from yoke_core.domain.path_claims_overlap import expand_lineage
    p = _p(conn)
    rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
        (downstream_claim_id,),
    ).fetchall()
    expanded = expand_lineage(conn, [int(t[0]) for t in rows])
    if not expanded:
        return None
    placeholders = ",".join(p for _ in expanded)
    candidates = conn.execute(
        f"SELECT DISTINCT pct.claim_id FROM path_claim_targets pct "
        f"JOIN path_claims pc ON pc.id = pct.claim_id "
        f"WHERE pc.integration_target = {p} "
        f"AND pc.state IN ('planned', 'blocked', 'active') "
        f"AND pc.mode <> 'exception' AND pc.id <> {p} "
        f"AND pct.target_id IN ({placeholders}) "
        f"ORDER BY pct.claim_id",
        (integration_target, downstream_claim_id, *expanded),
    ).fetchall()
    if not candidates:
        return None
    downstream_item = _claim_owning_item(conn, downstream_claim_id)
    if serial_only and downstream_item is None:
        return None
    if serial_only:
        from yoke_core.domain.path_claims_dependency_resolver_coordination import (
            has_forward_serial_edge,
        )
        for (cid,) in candidates:
            upstream_item = _claim_owning_item(conn, int(cid))
            if upstream_item is not None and has_forward_serial_edge(
                conn,
                dependent_item_id=downstream_item,
                blocking_item_id=upstream_item,
            ):
                return int(cid)
        return None
    return int(candidates[0][0])


def _emit_blocked_reason_refreshed(
    conn: Any, *, claim_id: int, item_id: Optional[int],
    prior_blocked_reason: str, new_blocked_reason: str,
    released_claim_id: int,
) -> None:
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return
    session_id = next(
        (os.environ[n] for n in (
            "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID",
        ) if os.environ.get(n)),
        "",
    )
    try:
        _native_emit(
            "PathClaimBlockedReasonRefreshed",
            event_kind="lifecycle", event_type="path_claim",
            source_type="system", session_id=session_id,
            severity="INFO", outcome="completed",
            project="yoke", item_id=item_id,
            context={
                "claim_id": claim_id,
                "prior_blocked_reason": prior_blocked_reason,
                "new_blocked_reason": new_blocked_reason,
                "released_claim_id": released_claim_id,
            },
            conn=conn,
        )
    except Exception:
        return


def propagate_release_unblock(
    conn: Any, *, released_claim_id: int,
) -> List[int]:
    """Re-classify downstream blocked claims after a release."""
    from yoke_core.domain.path_claims_overlap import (
        OverlapClassification,
        classify_overlap,
    )

    candidates = sorted(
        set(_direct_downstream_claims(conn, released_claim_id))
        | set(_dep_satisfied_downstream_claims(conn, released_claim_id))
    )
    flipped: List[int] = []
    for claim_id in candidates:
        p = _p(conn)
        row = conn.execute(
            f"SELECT state, integration_target FROM path_claims WHERE id = {p}",
            (claim_id,),
        ).fetchone()
        if row is None or str(row[0]) != "blocked":
            continue
        integration_target = str(row[1])
        target_rows = conn.execute(
            f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
            (claim_id,),
        ).fetchall()
        owning_item_id = conn.execute(
            f"SELECT item_id FROM path_claims WHERE id = {p}", (claim_id,),
        ).fetchone()
        candidate_item_id = (
            int(owning_item_id[0])
            if owning_item_id and owning_item_id[0] is not None
            else None
        )
        outcome = classify_overlap(
            conn,
            target_ids=[int(t[0]) for t in target_rows],
            integration_target=integration_target,
            upstream_claim_id=None,
            exclude_claim_id=claim_id,
            candidate_item_id=candidate_item_id,
            phase="register",
        )
        if outcome is OverlapClassification.NONE:
            conn.execute(
                "UPDATE path_claims SET state = 'planned', "
                f"blocked_reason = NULL WHERE id = {p}",
                (claim_id,),
            )
            flipped.append(claim_id)
        elif outcome is OverlapClassification.SERIAL_VIA_DEPENDENCY:
            refreshed = _refresh_blocked_reason(
                conn, claim_id=claim_id,
                integration_target=integration_target,
                released_claim_id=released_claim_id,
                serial_only=True,
            )
            if not refreshed:
                conn.execute(
                    "UPDATE path_claims SET state = 'planned', "
                    f"blocked_reason = NULL WHERE id = {p}",
                    (claim_id,),
                )
                flipped.append(claim_id)
        else:
            _refresh_blocked_reason(
                conn, claim_id=claim_id,
                integration_target=integration_target,
                released_claim_id=released_claim_id,
            )
    conn.commit()
    return flipped


def _refresh_blocked_reason(
    conn: Any, *, claim_id: int, integration_target: str,
    released_claim_id: int, serial_only: bool = False,
) -> bool:
    """Refresh blocked_reason to a surviving upstream when one remains."""
    p = _p(conn)
    row = conn.execute(
        f"SELECT blocked_reason, item_id FROM path_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    prior = str(row[0] or "") if row else ""
    item_id = int(row[1]) if row and row[1] is not None else None
    if _blocked_reason_claim_id(prior) != released_claim_id:
        return False
    new_id = _select_surviving_upstream(
        conn, downstream_claim_id=claim_id,
        integration_target=integration_target,
        serial_only=serial_only,
    )
    if new_id is None:
        return False
    new_reason = f"path_claims.id={new_id}"
    if new_reason == prior:
        return True
    conn.execute(
        f"UPDATE path_claims SET blocked_reason = {p} WHERE id = {p}",
        (new_reason, claim_id),
    )
    _emit_blocked_reason_refreshed(
        conn, claim_id=claim_id, item_id=item_id,
        prior_blocked_reason=prior, new_blocked_reason=new_reason,
        released_claim_id=released_claim_id,
    )
    return True


def unblock_stranded_for_released(
    conn: Any,
    *,
    claim_id: int | None = None,
) -> List[int]:
    """Recovery surface for stranded downstreams. Idempotent."""
    if claim_id is not None:
        p = _p(conn)
        released = conn.execute(
            f"SELECT state FROM path_claims WHERE id = {p}",
            (int(claim_id),),
        ).fetchone()
        if released is None or str(released[0]) != "released":
            return []
        return list(
            propagate_release_unblock(conn, released_claim_id=int(claim_id))
        )

    rows = conn.execute(
        "SELECT id FROM path_claims WHERE state = 'released' ORDER BY id",
    ).fetchall()
    flipped: List[int] = []
    for row in rows:
        released_id = int(row[0])
        flipped.extend(
            propagate_release_unblock(conn, released_claim_id=released_id)
        )
    return flipped


__all__ = ["propagate_release_unblock", "unblock_stranded_for_released"]
