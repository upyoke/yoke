"""Whether an item's selected delivery flow has actually delivered it.

One question, one answer, two readers. The terminal done engine and the
Dash completion gate both decide whether an item's delivery obligation is
discharged, and when they answer it from different reads they disagree about
the same release: two members of one succeeded run, one closed out and one
told to go deploy.

Membership is why. A run records the items it was started for, so an item
that landed into the same release without being enrolled has no membership
row — and a guard that reads only membership calls that "never deployed"
while the identical release closed its neighbour out. Enrolment is
bookkeeping about how a run was requested; it is not the fact the gate
means.

The fact the gate means is containment: does a succeeded run of this item's
selected flow ship a revision that already contains this item's merge? That
holds for every member of a batch rather than only the one that happens to
be the tip, and it holds whether or not anyone remembered to enrol it.

So the ladder is membership first — it is cheap, local, and the common case
— then containment. An unreadable containment source is ``undetermined``,
never ``not delivered``: a reader that could not look has learned nothing,
and refusing on that would strand correct releases for as long as the
provider is unwell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import (
    item_completion_flow,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    latest_completion_run,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED,
    candidate_contains_commit,
)
from yoke_core.domain.schema_common import _table_exists


DISCHARGED = "discharged"
NOT_DISCHARGED = "not_discharged"
UNDETERMINED_DELIVERY = "undetermined"

# How the verdict was reached, so a refusal can say which fact it read.
SOURCE_MEMBERSHIP = "run_membership"
SOURCE_CONTAINMENT = "release_containment"


@dataclass(frozen=True)
class DeliveryEvidence:
    """One delivery answer, with the run it rests on and why."""

    state: str
    run_id: str = ""
    run_status: str = ""
    source: str = ""
    reason: str = ""
    recovery: str = ""

    @property
    def discharged(self) -> bool:
        return self.state == DISCHARGED


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def item_merge_identity(conn: Any, item_id: int) -> str:
    """The merge commit this item's landing recorded, if it has one."""
    from yoke_core.domain.item_merge_receipt_document import landing_shas

    commit_sha, merge_sha = ("", "")
    shas = landing_shas(conn, int(item_id))
    if shas:
        commit_sha = shas[0]
        merge_sha = shas[1] if len(shas) > 1 else ""
    return merge_sha or commit_sha


def _project_id(conn: Any, item_id: int) -> Optional[int]:
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {_marker(conn)}",
        (int(item_id),),
    ).fetchone()
    return int(_cell(row, "project_id", 0)) if row is not None else None


def _succeeded_flow_runs(
    conn: Any, *, project_id: int, flow: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Recent succeeded runs of this flow, newest first.

    Newest first because the newest release contains the most merges, so the
    first rung of the containment walk answers almost every item. The limit
    only bounds how far back an unusually old landing is chased.
    """
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT id, COALESCE(release_lineage, '') AS release_lineage "
        "FROM deployment_runs "
        f"WHERE project_id = {marker} AND flow = {marker} "
        "AND status = 'succeeded' "
        f"ORDER BY created_at DESC, id DESC LIMIT {int(limit)}",
        (int(project_id), flow),
    ).fetchall()
    return [
        {
            "id": str(_cell(row, "id", 0) or ""),
            "release_lineage": str(_cell(row, "release_lineage", 1) or ""),
        }
        for row in rows
    ]


def delivery_evidence(conn: Any, item_id: int) -> DeliveryEvidence:
    """Whether the item's selected flow has delivered it, and on what."""
    required = ("deployment_runs", "deployment_run_items")
    if not all(_table_exists(conn, table) for table in required):
        return DeliveryEvidence(
            NOT_DISCHARGED,
            reason="this control plane records no deployment runs",
            recovery="Run the selected project delivery flow to completion.",
        )
    flow = item_completion_flow(conn, int(item_id))
    if not flow:
        return DeliveryEvidence(
            NOT_DISCHARGED,
            reason="the item selects no completion deployment flow",
            recovery=(
                "Set the item's deployment flow, or close it out through the "
                "merge-only delivery rung."
            ),
        )

    member = latest_completion_run(conn, int(item_id))
    if member is not None and str(member["status"]) == "succeeded":
        return DeliveryEvidence(
            DISCHARGED,
            run_id=str(member["id"]),
            run_status="succeeded",
            source=SOURCE_MEMBERSHIP,
        )

    merge_sha = item_merge_identity(conn, int(item_id))
    project_id = _project_id(conn, int(item_id))
    if not merge_sha or project_id is None:
        return _member_shaped_answer(member)

    undetermined: Optional[DeliveryEvidence] = None
    for run in _succeeded_flow_runs(conn, project_id=project_id, flow=flow):
        lineage = run["release_lineage"]
        if not lineage:
            continue
        verdict = candidate_contains_commit(
            conn,
            int(project_id),
            candidate_lineage=lineage,
            commit_sha=merge_sha,
        )
        if verdict.contained:
            return DeliveryEvidence(
                DISCHARGED,
                run_id=run["id"],
                run_status="succeeded",
                source=SOURCE_CONTAINMENT,
            )
        if verdict.state == UNDETERMINED and undetermined is None:
            # Remember the first unreadable comparison but keep walking: an
            # older run may still answer, and a definite yes beats an
            # unreadable maybe.
            undetermined = DeliveryEvidence(
                UNDETERMINED_DELIVERY,
                run_id=run["id"],
                source=SOURCE_CONTAINMENT,
                reason=(
                    "whether a succeeded release contains this item's merge "
                    f"could not be determined ({verdict.reason})"
                ),
                recovery=verdict.recovery,
            )
    if undetermined is not None:
        return undetermined
    return _member_shaped_answer(member)


def _member_shaped_answer(member: Optional[dict[str, Any]]) -> DeliveryEvidence:
    """The honest answer when no release contains this item's merge."""
    if member is None:
        return DeliveryEvidence(
            NOT_DISCHARGED,
            reason="no succeeded run of the selected flow contains this merge",
            recovery="Run the selected project delivery flow to completion.",
        )
    status = str(member["status"])
    return DeliveryEvidence(
        NOT_DISCHARGED,
        run_id=str(member["id"]),
        run_status=status,
        source=SOURCE_MEMBERSHIP,
        reason=f"the selected flow's latest run is at status {status!r}",
        recovery=(
            f"Execute or retry deployment run {member['id']}."
            if status in {"created", "executing"}
            else "Run the selected project delivery flow to completion."
        ),
    )


__all__ = [
    "DISCHARGED",
    "NOT_DISCHARGED",
    "SOURCE_CONTAINMENT",
    "SOURCE_MEMBERSHIP",
    "UNDETERMINED_DELIVERY",
    "DeliveryEvidence",
    "delivery_evidence",
    "item_merge_identity",
]
