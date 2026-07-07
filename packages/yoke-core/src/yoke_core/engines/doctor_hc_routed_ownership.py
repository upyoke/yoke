"""Routed-ownership doctor health checks.

Three read-only invariants on the routed-ownership defense backing
:func:`yoke_core.domain.frontier_recent_owner.routed_ownership_exclusions`.
All three read first-class claim/chain state (``work_claims.release_reason_intent``,
``harness_sessions.last_chain_step`` / ``last_checkpoint_at`` / ``offered_at``)
— never the events ledger. All three self-skip on minimal-schema fixtures
and never auto-fix.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import yoke_core.engines.doctor_report as _base
from yoke_core.domain import db_backend
from yoke_core.domain.frontier_recent_owner import routed_ownership_exclusions
from yoke_core.domain.release_intent_classification import (
    NON_TERMINAL_RELEASE_INTENTS,
)
from yoke_core.domain.runtime_settings import get_seconds
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_LIVE_FRAME_NAME = "HC-routed-ownership-live-frame-no-defense"
_HC_LIVE_FRAME_DESC = (
    "Live session with recent non-terminal release missing from defense map"
)
_HC_STILL_SCHED_NAME = "HC-routed-ownership-non-terminal-release-still-schedulable"
_HC_STILL_SCHED_DESC = (
    "Items with non-terminal release whose owner is live but still routable"
)
_HC_CLOBBER_NAME = "HC-offer-envelope-clobber-lost-chain"
_HC_CLOBBER_DESC = "Sessions whose chain_checkpoint was clobbered by a later offer"

_LIST_PREVIEW = 10

# Statuses where ``classify_next_action`` returns a non-WAIT/SKIP adapter.
_SCHEDULABLE_STATUSES = (
    "idea", "refining-idea", "refined-idea",
    "planning", "plan-drafted", "refining-plan", "planned",
    "implementing", "reviewing-implementation",
    "reviewed-implementation", "polishing-implementation",
    "implemented", "release",
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _required_tables_present(conn: Any) -> bool:
    return all(
        _base._table_exists(conn, t)
        for t in ("harness_sessions", "work_claims")
    )


def _column_present(conn: Any, table: str, column: str) -> bool:
    from yoke_core.domain.schema_common import _get_columns

    try:
        return column in set(_get_columns(conn, table))
    except db_backend.operational_error_types(conn):
        return False


def _emit_warn(
    rec: RecordCollector, name: str, desc: str,
    summary: str, lines: List[str],
) -> None:
    issues = [summary] + lines[:_LIST_PREVIEW]
    if len(lines) > _LIST_PREVIEW:
        issues.append(f"  ... and {len(lines) - _LIST_PREVIEW} more")
    rec.record(name, desc, "WARN", "\n".join(issues))


def _live_non_terminal_releases(conn: Any) -> List[Any]:
    """Live sessions with a non-terminal release intent on a released claim.

    Reads ``work_claims.release_reason_intent`` — first-class claim state
    stamped by the release paths (mirrors ``frontier_recent_owner``).
    Fixture schemas without the column yield no rows: NULL intent means
    "no state recorded", never a reason to consult the events ledger.
    """
    if not _column_present(conn, "work_claims", "release_reason_intent"):
        return []
    sql = """
    SELECT
        hs.session_id AS session_id,
        wc.id AS claim_id,
        wc.item_id AS item_id,
        wc.released_at AS released_at,
        hs.last_heartbeat AS last_heartbeat,
        wc.release_reason_intent AS release_intent
    FROM harness_sessions hs
    JOIN work_claims wc ON wc.session_id = hs.session_id
    WHERE hs.ended_at IS NULL
      AND wc.target_kind = 'item'
      AND wc.item_id IS NOT NULL
      AND wc.released_at IS NOT NULL
      AND wc.release_reason_intent IS NOT NULL
    """
    out: List[Any] = []
    for row in conn.execute(sql).fetchall():
        intent = row["release_intent"]
        if intent and intent in NON_TERMINAL_RELEASE_INTENTS:
            out.append(row)
    return out


def hc_routed_ownership_live_frame_no_defense(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """WARN when a live non-terminal release is missing from the defense map."""
    if not _required_tables_present(conn):
        rec.record(_HC_LIVE_FRAME_NAME, _HC_LIVE_FRAME_DESC, "PASS",
                   "required tables missing — skipping")
        return

    window_s = get_seconds("session_reactivation_reacquire_window_s", 300)
    # Call oracle with requesting_session_id=None so no live session
    # is filtered from the defense map (self-exclusion trap).
    defended = routed_ownership_exclusions(
        conn, window_s=window_s, requesting_session_id=None,
    )
    defended_items: Dict[int, dict] = {}
    for d in defended.values():
        try:
            defended_items[int(str(d["item_id"]).replace("YOK-", ""))] = d
        except (ValueError, TypeError):
            continue

    lines: List[str] = []
    missing_count = 0
    for row in _live_non_terminal_releases(conn):
        item_id = row["item_id"]
        if item_id is None or int(item_id) in defended_items:
            continue
        missing_count += 1
        lines.append(
            f"  - session={row['session_id']} item=YOK-{int(item_id)} "
            f"claim_id={int(row['claim_id'])} "
            f"intent={row['release_intent']}"
        )

    if missing_count == 0:
        rec.record(_HC_LIVE_FRAME_NAME, _HC_LIVE_FRAME_DESC, "PASS", "")
        return

    summary = (
        f"- {missing_count} live session(s) with a recent non-terminal "
        "release that the routed-ownership defense does NOT name. The "
        "second session may re-route the same item. Operator recovery: "
        "`python3 -m yoke_core.api.service_client release-work-claim "
        "--allow-non-terminal --item YOK-N --reason '...'`."
    )
    _emit_warn(rec, _HC_LIVE_FRAME_NAME, _HC_LIVE_FRAME_DESC, summary, lines)


def hc_routed_ownership_non_terminal_release_still_schedulable(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """WARN when a non-terminal-released item remains effectively routable."""
    if not _required_tables_present(conn):
        rec.record(_HC_STILL_SCHED_NAME, _HC_STILL_SCHED_DESC, "PASS",
                   "required tables missing — skipping")
        return
    if not _base._table_exists(conn, "items"):
        rec.record(_HC_STILL_SCHED_NAME, _HC_STILL_SCHED_DESC, "PASS",
                   "items table missing — skipping")
        return

    rows = _live_non_terminal_releases(conn)
    if not rows:
        rec.record(_HC_STILL_SCHED_NAME, _HC_STILL_SCHED_DESC, "PASS", "")
        return

    window_s = get_seconds("session_reactivation_reacquire_window_s", 300)
    defended = routed_ownership_exclusions(
        conn, window_s=window_s, requesting_session_id=None,
    )
    defended_item_ids: set[int] = set()
    for detail in defended.values():
        try:
            defended_item_ids.add(int(str(detail["item_id"]).replace("YOK-", "")))
        except (KeyError, TypeError, ValueError):
            continue

    p = _p(conn)
    placeholders = ",".join([p] * len(_SCHEDULABLE_STATUSES))
    routable_sql = (
        f"SELECT id, status FROM items WHERE id = {p} AND status IN ({placeholders})"
    )

    lines: List[str] = []
    hit_count = 0
    for row in rows:
        item_id = row["item_id"]
        if item_id is None:
            continue
        if int(item_id) in defended_item_ids:
            continue
        match = conn.execute(
            routable_sql, (int(item_id), *_SCHEDULABLE_STATUSES),
        ).fetchone()
        if match is None:
            continue
        hit_count += 1
        lines.append(
            f"  - YOK-{int(item_id)} status={match['status']} "
            f"owner={row['session_id']} intent={row['release_intent']}"
        )

    if hit_count == 0:
        rec.record(_HC_STILL_SCHED_NAME, _HC_STILL_SCHED_DESC, "PASS", "")
        return

    summary = (
        f"- {hit_count} item(s) carry a non-terminal release whose owner "
        "is still live, yet sit in a routable status. The router may "
        "offer them to a second session before the defense window expires."
    )
    _emit_warn(rec, _HC_STILL_SCHED_NAME, _HC_STILL_SCHED_DESC, summary, lines)


def _envelope_checkpoint_step(envelope_raw: Optional[str]) -> Optional[int]:
    if not envelope_raw:
        return None
    try:
        env = json.loads(envelope_raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    checkpoint = env.get("chain_checkpoint") if isinstance(env, dict) else None
    if not isinstance(checkpoint, dict):
        return None
    step = checkpoint.get("step")
    if isinstance(step, int):
        return step
    if isinstance(step, str) and step.isdigit():
        return int(step)
    return None


# Chain progress comes from the first-class session columns stamped by
# the chain-checkpoint writer (``last_chain_step`` / ``last_checkpoint_at``
# survive envelope rewrites). A clobber is structural: the live
# ``offer_envelope`` carries a lower ``chain_checkpoint.step`` than the
# session's authoritative ``last_chain_step`` (or none at all) — a later
# offer replaced the envelope wholesale. No offer-time comparison is
# needed: state-to-state comparison subsumes the old time proxy.
_CLOBBER_SQL = """
SELECT
    hs.session_id AS session_id,
    hs.offered_at AS offered_at,
    hs.offer_envelope AS offer_envelope,
    hs.last_chain_step AS max_step,
    hs.last_checkpoint_at AS last_checkpoint_at
FROM harness_sessions hs
WHERE hs.last_chain_step IS NOT NULL
"""


def hc_offer_envelope_clobber_lost_chain(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """WARN when a session's chain_checkpoint was clobbered by a later offer."""
    if not _required_tables_present(conn):
        rec.record(_HC_CLOBBER_NAME, _HC_CLOBBER_DESC, "PASS",
                   "required tables missing — skipping")
        return
    if not _column_present(conn, "harness_sessions", "last_chain_step"):
        rec.record(_HC_CLOBBER_NAME, _HC_CLOBBER_DESC, "PASS",
                   "chain-state columns missing — skipping")
        return

    lines: List[str] = []
    hit_count = 0
    min_offered_at = _base._read_str_cutoff(
        "hc_offer_envelope_clobber_min_session_created_at",
    )
    for row in conn.execute(_CLOBBER_SQL).fetchall():
        if min_offered_at and (row["offered_at"] or "") < min_offered_at:
            continue
        max_step = row["max_step"]
        if max_step is None:
            continue
        current_step = _envelope_checkpoint_step(row["offer_envelope"])
        if current_step is not None and current_step >= int(max_step):
            continue
        hit_count += 1
        cur = current_step if current_step is not None else "absent"
        lines.append(
            f"  - session={row['session_id']} max_step={int(max_step)} "
            f"current_step={cur} "
            f"last_checkpoint_at={row['last_checkpoint_at']}"
        )

    if hit_count == 0:
        rec.record(_HC_CLOBBER_NAME, _HC_CLOBBER_DESC, "PASS", "")
        return

    summary = (
        f"- {hit_count} session(s) lost their chain_checkpoint to a later "
        "offer write. Operator recovery (chain-end override): "
        "`python3 -m yoke_core.api.service_client session-end "
        "--override-chain-end --chain-end-rationale '...' --session-id S`."
    )
    _emit_warn(rec, _HC_CLOBBER_NAME, _HC_CLOBBER_DESC, summary, lines)


__all__ = [
    "hc_routed_ownership_live_frame_no_defense",
    "hc_routed_ownership_non_terminal_release_still_schedulable",
    "hc_offer_envelope_clobber_lost_chain",
]
