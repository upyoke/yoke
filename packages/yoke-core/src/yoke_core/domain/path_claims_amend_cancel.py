"""Cancel-amendment helper for the path-claim amendment surface.

Splits out of :mod:`yoke_core.domain.path_claims_amend` to keep the
parent module within its line budget. Owns ``cancel_amendment`` and
the small inverse-mutation helpers it depends on. The parent module
re-exports the public symbol.

Append-only contract: the original amendment row stays. The cancel
record carries the cancelled amendment id, the original kind, and the
original payload so the audit trail is reconstructable from the
amendment chain alone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import PathClaimError, get_claim


class AmendmentNotFound(PathClaimError):
    """The amendment id does not exist for the given claim."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _executemany(conn: Any, sql: str, rows: Sequence[tuple]) -> None:
    if db_backend.connection_is_postgres(conn):
        target = getattr(conn, "_inner", conn)
        with target.cursor() as cur:
            cur.executemany(sql, rows)
        return
    if hasattr(conn, "executemany"):
        conn.executemany(sql, rows)
        return
    raise AttributeError("connection does not support executemany")


def _record_cancel(
    conn: Any,
    *,
    claim_id: int,
    payload: dict,
    reason: str,
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_claim_amendments "
        "(claim_id, amended_at, amendment_kind, payload, reason) "
        f"VALUES ({p}, {p}, 'cancel', {p}, {p}) RETURNING id",
        (claim_id, _now(), json.dumps(payload), reason),
    )
    return int(cur.fetchone()[0])


def _existing_targets(
    conn: Any, claim_id: int
) -> List[int]:
    p = _p(conn)
    return [
        int(r[0])
        for r in conn.execute(
            "SELECT target_id FROM path_claim_targets "
            f"WHERE claim_id = {p} ORDER BY id",
            (claim_id,),
        )
    ]


def _undo_widen(
    conn: Any, claim_id: int, payload: dict
) -> None:
    added_ids = [int(t) for t in payload.get("added") or []]
    if not added_ids:
        return
    p = _p(conn)
    placeholders = ",".join(p for _ in added_ids)
    conn.execute(
        f"DELETE FROM path_claim_targets "
        f"WHERE claim_id = {p} AND target_id IN ({placeholders})",
        (claim_id, *added_ids),
    )


def _undo_narrow(
    conn: Any, claim_id: int, payload: dict
) -> None:
    removed_ids = [int(t) for t in payload.get("removed") or []]
    if not removed_ids:
        return
    existing = set(_existing_targets(conn, claim_id))
    now = _now()
    rows = []
    for tid in removed_ids:
        if tid in existing:
            continue
        p = _p(conn)
        present = conn.execute(
            f"SELECT 1 FROM path_targets WHERE id = {p}", (tid,)
        ).fetchone()
        if present is None:
            # The target was hard-deleted from the registry between the
            # original narrow and the cancel; the cancel still lands
            # but the inverse mutation is skipped for that target. The
            # operator routes via release/re-register for the
            # unrecoverable subset.
            continue
        rows.append((claim_id, tid, now))
    if rows:
        p = _p(conn)
        _executemany(
            conn,
            "INSERT INTO path_claim_targets "
            f"(claim_id, target_id, declared_at) VALUES ({p}, {p}, {p})",
            rows,
        )


def cancel_amendment(
    conn: Any,
    *,
    claim_id: int,
    amendment_id: int,
    reason: str,
) -> int:
    """Append a ``cancel`` record that names the amendment being undone."""
    get_claim(conn, claim_id)
    p = _p(conn)
    row = conn.execute(
        "SELECT amendment_kind, payload FROM path_claim_amendments "
        f"WHERE id = {p} AND claim_id = {p}",
        (amendment_id, claim_id),
    ).fetchone()
    if row is None:
        raise AmendmentNotFound(
            f"amendment id {amendment_id} not found for claim {claim_id}"
        )
    kind = str(row[0])
    payload = json.loads(row[1] or "{}")
    if kind == "widen":
        _undo_widen(conn, claim_id, payload)
    elif kind == "narrow":
        _undo_narrow(conn, claim_id, payload)
    new_id = _record_cancel(
        conn,
        claim_id=claim_id,
        payload={
            "cancelled_amendment_id": amendment_id,
            "cancelled_kind": kind,
            "cancelled_payload": payload,
        },
        reason=reason,
    )
    conn.commit()
    return new_id


__all__ = [
    "AmendmentNotFound",
    "cancel_amendment",
]
