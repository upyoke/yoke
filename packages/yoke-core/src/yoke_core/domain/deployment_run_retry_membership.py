"""Carry a retried run's frozen membership onto its replacement run.

A retry re-runs one candidate that already failed: the same pinned release
lineage, the same artifact, and therefore the same items. Creating it without
that membership turned the sanctioned recovery for a failed item deploy into
an environment-level release, and the item it was recovering could never reach
its completion gate no matter how often its deployment actually succeeded.

The membership is copied, never recomputed. Re-deriving it from whatever main
holds now would attach items the retried candidate does not contain, and the
frozen requirement snapshot is the candidate's own acceptance contract — it
travels with the candidate. It carries no verdict: what each member must still
prove moves, what an earlier run proved does not.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from yoke_core.domain.db_helpers import connect, iso8601_now


MEMBER_COLUMNS = (
    "item_id",
    "delivery_intent",
    "requirement_selection",
    "requirement_snapshot",
)


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def frozen_members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Return one run's member rows in a stable order."""
    rows = conn.execute(
        f"SELECT {','.join(MEMBER_COLUMNS)} FROM deployment_run_items "
        "WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return [
        {column: _cell(row, column, index) for index, column in enumerate(MEMBER_COLUMNS)}
        for row in rows
    ]


def inherit_retry_membership(
    source_run_id: str,
    target_run_id: str,
    *,
    db_path: Optional[str] = None,
) -> tuple[int, ...]:
    """Copy the retried run's members onto the retry. Returns the item ids.

    An environment-level source has no members, so its retry stays
    environment-level: the empty copy is the correct answer rather than a
    reason to look elsewhere for membership.
    """
    conn = connect(db_path)
    try:
        members = frozen_members(conn, source_run_id)
        added_at = iso8601_now()
        for member in members:
            conn.execute(
                "INSERT INTO deployment_run_items "
                "(run_id, item_id, added_at, delivery_intent, "
                "requirement_selection, requirement_snapshot) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    target_run_id,
                    member["item_id"],
                    added_at,
                    member["delivery_intent"],
                    member["requirement_selection"],
                    member["requirement_snapshot"],
                ),
            )
        conn.commit()
        return tuple(int(member["item_id"]) for member in members)
    finally:
        conn.close()


def candidate_mismatch_refusal(
    source_lineage: str,
    source_artifact: Optional[str],
    *,
    release_lineage: str,
    artifact_identity: Optional[str],
) -> Optional[str]:
    """Refuse a retry whose candidate is not the one that failed.

    Inheriting membership is only sound because the candidate is identical. A
    different revision or artifact is a replacement release and needs its own
    membership decision, so it is named as one rather than quietly inheriting.
    """
    if _normalized(release_lineage) != _normalized(source_lineage):
        return (
            "retry candidate mismatch: the retried run is pinned to "
            f"{source_lineage!r} and this request pins {release_lineage!r}; "
            "start a new run for a different revision instead of retrying"
        )
    if _normalized(artifact_identity) != _normalized(source_artifact):
        return (
            "retry candidate mismatch: the retried run's artifact identity "
            "differs from this request's; start a new run for a different "
            "artifact instead of retrying"
        )
    return None


def _normalized(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "MEMBER_COLUMNS",
    "candidate_mismatch_refusal",
    "frozen_members",
    "inherit_retry_membership",
]
