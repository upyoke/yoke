"""Carry a retried run's frozen membership onto its replacement run.

A retry re-runs one candidate that already failed: the same pinned release
lineage and artifact, with the previous admission for items that are not frozen. Creating it without
that membership turned the sanctioned recovery for a failed item deploy into
an environment-level release, and the item it was recovering could never reach
its completion gate no matter how often its deployment actually succeeded.

Eligible membership is copied, never recomputed. Re-deriving it from whatever main
holds now would attach items the retried candidate does not contain, and the
frozen requirement snapshot is the candidate's own acceptance contract — it
travels with the candidate. It carries no verdict: what each member must still
prove moves, what an earlier run proved does not.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.deployment_run_landed_closeout import flag_frozen_item_ids


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
        {
            column: _cell(row, column, index)
            for index, column in enumerate(MEMBER_COLUMNS)
        }
        for row in rows
    ]


def copy_frozen_members(
    conn: Any,
    source_run_id: str,
    target_run_id: str,
) -> tuple[int, ...]:
    """Copy eligible members to the retry in the caller's transaction.

    The retry stays environment-level when the source has no members or
    every source member is frozen.
    """
    members = frozen_members(conn, source_run_id)
    frozen_ids = flag_frozen_item_ids(
        conn, (int(member["item_id"]) for member in members)
    )
    members = [member for member in members if int(member["item_id"]) not in frozen_ids]
    added_at = instant_parameter(conn, utc_now())
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
    return tuple(int(member["item_id"]) for member in members)


def candidate_mismatch_refusal(
    source_lineage: str,
    source_artifact: str | None,
    *,
    release_lineage: str,
    artifact_identity: str | None,
) -> str | None:
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
    "copy_frozen_members",
    "frozen_members",
]
