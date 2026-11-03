"""Read only path claims relevant to the selected session holdings."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_holdings_claim_facts import clear_failed_read


def path_rows(
    conn: Any,
    *,
    claims: Sequence[Mapping[str, Any]],
    session_ids: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    clauses = ["pc.released_at IS NULL AND pc.cancelled_at IS NULL"]
    params: list[Any] = []
    if session_ids is not None:
        selections = (
            ("pc.owner_session_id", session_ids),
            ("pc.owner_item_id", tuple({
                int(claim["item_id"]) for claim in claims
                if claim.get("target_kind") == "item"
                and claim.get("item_id") is not None
            })),
            ("pc.owner_work_claim_id", tuple(int(claim["id"]) for claim in claims)),
        )
        for column, values in selections:
            if values:
                markers = ",".join("%s" for _ in values)
                clauses.append(f"{column} IN ({markers})")
                params.extend(values)
    where = "WHERE " + " OR ".join(f"({clause})" for clause in clauses)
    if session_ids is None:
        where = ""
    try:
        rows = conn.execute(
            "WITH selected AS ("
            "SELECT pc.id,pc.owner_kind,pc.owner_item_id,pc.owner_session_id,"
            "pc.owner_work_claim_id,pc.released_at,pc.cancelled_at "
            f"FROM path_claims pc {where}), "
            "counts AS (SELECT pct.claim_id,COUNT(*) AS declared_count "
            "FROM path_claim_targets pct JOIN selected ON selected.id=pct.claim_id "
            "GROUP BY pct.claim_id) "
            "SELECT selected.*,COALESCE(counts.declared_count,0) AS declared_count "
            "FROM selected LEFT JOIN counts ON counts.claim_id=selected.id "
            "ORDER BY selected.id DESC",
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]
    except db_backend.database_error_types(conn):
        clear_failed_read(conn)
        return []
