"""Listing and liveness diagnostics for shared-operation work claims.

Sibling of :mod:`yoke_core.domain.coordination_claims`. Owns the read
helpers doctor, operator, and board consumers use to inspect active,
released, and stale-candidate claims without dropping to raw SQL. Pure
reads; no mutation, no auto-release.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_keys import (
    COORDINATION_TARGET_KINDS,
    kind_for_key,
)
from yoke_core.domain.coordination_claim_record import (
    FROM_CLAUSE,
    SELECT_COLUMNS,
    CoordinationClaim,
    row_to_claim,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.work_claim_target_sql import scope_text_sql

_KINDS_SQL = ", ".join(f"'{kind}'" for kind in sorted(COORDINATION_TARGET_KINDS))


def _kind_filter(alias: str = "wc") -> str:
    return f"{alias}.target_kind IN ({_KINDS_SQL})"


def list_claims(
    conn: Any,
    *,
    project_id: Optional[Union[str, int]] = None,
    key: Optional[str] = None,
    session_id: Optional[str] = None,
    owner_item_id: Optional[int] = None,
    active_only: bool = False,
) -> List[CoordinationClaim]:
    """Read helper for inspecting shared-operation claims without raw SQL.

    Filters compose with AND. ``active_only`` restricts to non-released
    rows — the same predicate doctor and the board's claims column use
    when rendering live ownership.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    where: List[str] = [_kind_filter()]
    params: List[Any] = []
    if project_id is not None:
        where.append(f"{scope_text_sql(conn, 'wc.scope', 'project_id')} = {p}")
        params.append(str(resolve_project_id(conn, project_id)))
    if key is not None:
        kind = kind_for_key(key)
        if kind is None:
            return []
        where.append(f"wc.target_kind = {p}")
        params.append(kind)
        suffix = _key_suffix_column(kind)
        where.append(f"{scope_text_sql(conn, 'wc.scope', suffix[0])} = {p}")
        params.append(str(key)[suffix[1]:])
    if session_id is not None:
        where.append(f"wc.session_id = {p}")
        params.append(session_id)
    if owner_item_id is not None:
        where.append(f"{scope_text_sql(conn, 'wc.scope', 'item_id')} = {p}")
        params.append(str(int(owner_item_id)))
    if active_only:
        where.append("wc.released_at IS NULL")
    rows = conn.execute(
        f"SELECT {SELECT_COLUMNS} {FROM_CLAUSE} WHERE "
        + " AND ".join(where)
        + " ORDER BY wc.claimed_at DESC, wc.id DESC",
        tuple(params),
    ).fetchall()
    return [row_to_claim(row) for row in rows]


def _key_suffix_column(kind: str) -> tuple[str, int]:
    """Return the scope key and key-prefix length identifying one kind."""
    from yoke_core.domain.coordination_claim_keys import (
        MIGRATION_KEY_PREFIX,
        QA_HOST_KEY_PREFIX,
        QUALIFICATION_KEY_PREFIX,
    )
    from yoke_core.domain.work_claim_targets import (
        TARGET_KIND_MIGRATION_SERIALIZATION,
        TARGET_KIND_QA_ADMISSION,
    )

    if kind == TARGET_KIND_MIGRATION_SERIALIZATION:
        return ("model", len(MIGRATION_KEY_PREFIX))
    if kind == TARGET_KIND_QA_ADMISSION:
        return ("machine_id", len(QA_HOST_KEY_PREFIX))
    return ("grant_key", len(QUALIFICATION_KEY_PREFIX))


def stale_claim_candidates(
    conn: Any,
    *,
    threshold_iso: str,
    project_id: Optional[Union[str, int]] = None,
) -> List[CoordinationClaim]:
    """Return active claims whose heartbeat predates ``threshold_iso``.

    Pure diagnostic surface — no auto-release. Doctor consumes this and
    surfaces recovery candidates; operators recover through
    :func:`yoke_core.domain.coordination_claims_operator.operator_release`.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    where = [
        _kind_filter(),
        "wc.released_at IS NULL",
        f"(wc.last_heartbeat IS NULL OR wc.last_heartbeat < {p})",
    ]
    params: List[Any] = [threshold_iso]
    if project_id is not None:
        where.append(f"{scope_text_sql(conn, 'wc.scope', 'project_id')} = {p}")
        params.append(str(resolve_project_id(conn, project_id)))
    rows = conn.execute(
        f"SELECT {SELECT_COLUMNS} {FROM_CLAUSE} WHERE "
        + " AND ".join(where)
        + " ORDER BY wc.last_heartbeat ASC, wc.id ASC",
        tuple(params),
    ).fetchall()
    return [row_to_claim(row) for row in rows]


__all__ = ["list_claims", "stale_claim_candidates"]
