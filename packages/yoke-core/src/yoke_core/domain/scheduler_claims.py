"""Scheduler work-claim state evaluation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db_backend
from .scheduler_types import ClaimState
from .yok_n_parser import parse_item_id_or_none
from yoke_core.domain.schema_work_claim_sql import scope_int_sql


def _evaluate_claim_states(
    conn: Any,
    item_ids: List[int],
    session_id: Optional[str] = None,
    target_kind: str = "item",
) -> Dict[int, ClaimState]:
    """Evaluate claim state for a list of internal item ids.

    Returns a dict mapping internal ``items.id`` -> ClaimState. With
    ``target_kind="epic_task"`` the ids are epics and the state is that of
    the claims on their tasks, keyed by the claim scope's ``epic_id``.
    """
    if not item_ids:
        return {}

    result: Dict[int, ClaimState] = {iid: ClaimState.UNCLAIMED for iid in item_ids}

    claim_rows = None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    scope_key = "epic_id" if target_kind == "epic_task" else "item_id"
    try:
        # Prefer the richer join when the full session schema is available.
        # One target kind per call: the scheduler's item claim state reads
        # item targets; task holders are a separate staffing fact. Only a
        # terminal stamp makes an active claim assignable to another session.
        item_scope = scope_int_sql(conn, "wc.scope", scope_key)
        claim_rows = conn.execute(
            f"""SELECT {item_scope} AS item_id, wc.session_id,
                      COALESCE(ases.ended_at, ases.terminated_at) AS session_ended_at
               FROM work_claims wc
               LEFT JOIN harness_sessions ases ON ases.session_id = wc.session_id
               WHERE wc.released_at IS NULL
                 AND wc.target_kind={marker}""",
            (target_kind,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            # Some test and transitional schemas have a partial work_claims
            # table; still treat non-self live item claims as blocking.
            item_scope = scope_int_sql(conn, "scope", scope_key)
            claim_rows = conn.execute(
                f"""SELECT {item_scope} AS item_id, session_id
                   FROM work_claims
                   WHERE released_at IS NULL
                     AND target_kind={marker}""",
                (target_kind,),
            ).fetchall()
        except db_backend.operational_error_types(conn):
            if db_backend.connection_is_postgres(conn):
                try:
                    conn.rollback()
                except Exception:
                    pass
            return result  # Tables may not exist

    for row in claim_rows:
        raw_item_id = row[0]
        if raw_item_id is None:
            continue
        # Production storage is the bare internal integer; legacy fixture
        # rows may still hold ``YOK-N`` TEXT, which resolves through the
        # canonical parser (prefix + project_sequence). The bare internal
        # id matches the scheduler's caller-provided item keys.
        resolved_item = parse_item_id_or_none(raw_item_id, conn=conn)
        if resolved_item is None:
            continue
        item_id = int(resolved_item)
        claim_session = row[1]
        # An epic's tasks carry several claims; a live other holder wins.
        if result.get(item_id, ClaimState.CLAIMED_BY_OTHER_LIVE) is (
            ClaimState.CLAIMED_BY_OTHER_LIVE
        ):
            continue

        session_ended = row[2] if len(row) > 2 else None
        if session_id and claim_session == session_id:
            result[item_id] = ClaimState.CLAIMED_BY_SELF
        elif session_ended is not None:
            result[item_id] = ClaimState.CLAIMED_BY_ENDED
        else:
            result[item_id] = ClaimState.CLAIMED_BY_OTHER_LIVE

    return result
