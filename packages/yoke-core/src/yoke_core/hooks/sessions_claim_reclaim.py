"""Race-safe stale-holder reclamation during work-claim acquisition."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.session_reclaim_activity import (
    SCOPE_ITEM_CLAIM,
    classify_reclaimable,
)
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_ITEM,
    WorkClaimTarget,
)

from yoke_core.hooks.sessions_event_emit import _emit_event


def reclaim_stale_conflicts(
    conn: Any,
    conflict_claims: list[Any],
    *,
    target: WorkClaimTarget,
    target_label: str,
    attempting_session_id: str,
    now: str,
) -> tuple[str, ...]:
    """Revalidate and release holders stale in the initial snapshot.

    Returns the sessions whose claim was actually reclaimed, so the
    caller can release their item focus once this claim-row transaction
    has committed.
    """
    snapshot_stale_claims = [
        row
        for row in conflict_claims
        if row[2] is not None
        or (
            activity_is_stale(row[4], executor=row[3])
            and activity_is_stale(row[5], executor=row[3])
        )
    ]
    item_id = str(target.item_id) if target.kind == TARGET_KIND_ITEM else None
    reclaimed_holders: list[str] = []
    for claim in snapshot_stale_claims:
        original_session_id = claim[1]
        recheck = classify_reclaimable(
            conn,
            original_session_id,
            claim_id=claim[0],
        )
        if not recheck.is_reclaimable:
            evidence = recheck.evidence.as_payload()
            _emit_event(
                conn,
                original_session_id,
                "ReclaimAborted",
                json.dumps(
                    {
                        "claim_id": claim[0],
                        "scope": SCOPE_ITEM_CLAIM,
                        "original_session_id": original_session_id,
                        "attempting_session_id": attempting_session_id,
                        "abort_reason": recheck.reason,
                        "executor": evidence["executor"],
                        "effective_ttl_minutes": evidence["effective_ttl_minutes"],
                        "original_session_last_heartbeat": evidence["last_heartbeat"],
                        "original_session_last_event_at": evidence["last_event_at"],
                        "target_kind": target.kind,
                        "target_label": target_label,
                    }
                ),
                item_id=item_id,
            )
            continue
        conn.execute(
            "UPDATE work_claims SET released_at=%s, release_reason='reclaimed' "
            "WHERE id=%s AND released_at IS NULL",
            (now, claim[0]),
        )
        reclaimed_holders.append(str(original_session_id))
        _emit_event(
            conn,
            original_session_id,
            "WorkReclaimed",
            json.dumps(
                {
                    "claim_id": claim[0],
                    "reason": "stale_item_claim_reclaimed",
                    "target_kind": target.kind,
                    "target_label": target_label,
                }
            ),
            item_id=item_id,
        )
    return tuple(reclaimed_holders)


__all__ = ["reclaim_stale_conflicts"]
