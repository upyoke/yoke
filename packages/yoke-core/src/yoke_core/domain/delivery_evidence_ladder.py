"""Whether a release has actually delivered one item.

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

Containment is what answers when membership does not: does a succeeded
release ship a revision that already contains this item's merge? That holds
for every member of a batch rather than only the one that happens to be the
tip, and it holds whether or not anyone remembered to enrol it.

"A succeeded release" is wider than this item's own flow, and wider still
for an item that stores no flow at all — one some workflow never recorded
and offers no way to set afterwards, which read as "not delivered" and
stranded it at its release wait even after a release in its own project had
carried its merge. Which releases each of those two may be asked about is
its own decision, and :mod:`delivery_release_candidates` owns it.

So the ladder is membership first — it is cheap, local, and the common case
— then containment. An unreadable containment source is ``undetermined``,
never ``not delivered``: a reader that could not look has learned nothing,
and refusing on that would strand correct releases for as long as the
provider is unwell.

This answers "has delivery happened", and nothing stricter. A caller may
have a stricter question — Dash completion posture additionally requires the
deployed candidate to contain the item's merge and its live lane head — so
the verdict carries the candidate the run recorded for this item's project,
for that caller to judge, rather than folding two different questions into
one answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.delivery_release_candidates import (
    row_cell as _cell,
    sql_marker as _marker,
    succeeded_flow_runs,
    succeeded_persistent_runs,
)
from yoke_core.domain.deployment_item_flow_resolution import (
    item_completion_flow,
)
from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
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
    # The candidate this run recorded for the item's own project, plus that
    # project, so a caller with a STRICTER question than "did delivery
    # happen" can ask it of the same release. The Dash completion posture is
    # that caller: it additionally requires the deployed candidate to
    # contain the item's merge and live lane head.
    #
    # Carried on every answer that names a run, not only on a discharged
    # one. A client standing in the lane answers containment for a control
    # plane that cannot, and it can only do that against a candidate it was
    # told about — so withholding the candidate from the unread and
    # not-yet-delivered answers made that relay unreachable in exactly the
    # cases it exists for.
    release_lineage: str = ""
    project_id: Optional[int] = None

    @property
    def discharged(self) -> bool:
        return self.state == DISCHARGED


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


def delivery_evidence(conn: Any, item_id: int) -> DeliveryEvidence:
    """Whether a succeeded release has delivered this item, and on what."""
    required = ("deployment_runs", "deployment_run_items")
    if not all(_table_exists(conn, table) for table in required):
        return DeliveryEvidence(
            NOT_DISCHARGED,
            reason="this control plane records no deployment runs",
            recovery="Run the selected project delivery flow to completion.",
        )
    # An item with no stored flow has no membership rung to stand on —
    # ``latest_completion_run`` keys off that same flow — so its answer comes
    # from the containment walk below.
    flow = item_completion_flow(conn, int(item_id))

    member = latest_completion_run(conn, int(item_id))
    if member is not None and str(member["status"]) == "succeeded":
        # Membership answers the delivery question on its own, as it always
        # has. It does not answer the containment question, which is why the
        # run's own candidate travels with the verdict rather than being
        # treated as already checked.
        return DeliveryEvidence(
            DISCHARGED,
            run_id=str(member["id"]),
            run_status="succeeded",
            source=SOURCE_MEMBERSHIP,
            release_lineage=str(member.get("release_lineage") or ""),
            project_id=member.get("project_id"),
        )
    if member is not None and independent_member_delivery_ready(
        conn, item_id=int(item_id), run_id=str(member["id"])
    ):
        return DeliveryEvidence(
            DISCHARGED,
            run_id=str(member["id"]),
            run_status="executing",
            source=SOURCE_MEMBERSHIP,
            release_lineage=str(member.get("release_lineage") or ""),
            project_id=member.get("project_id"),
        )

    merge_sha = item_merge_identity(conn, int(item_id))
    project_id = _project_id(conn, int(item_id))
    if not merge_sha or project_id is None:
        return _member_shaped_answer(member, flow=flow)

    releases = (
        succeeded_flow_runs(conn, project_id=project_id, flow=flow)
        if flow
        else succeeded_persistent_runs(conn, project_id=project_id)
    )
    undetermined: Optional[DeliveryEvidence] = None
    for run in releases:
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
                release_lineage=lineage,
                project_id=int(project_id),
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
                release_lineage=lineage,
                project_id=int(project_id),
            )
    if undetermined is not None:
        return undetermined
    return _member_shaped_answer(member, flow=flow)


def _member_shaped_answer(
    member: Optional[dict[str, Any]],
    *,
    flow: str = "",
) -> DeliveryEvidence:
    """The honest answer when no release contains this item's merge."""
    if member is None and not flow:
        # Say which question was asked, so the refusal is not read as the
        # old dead end of "this item selects no flow, and never will".
        return DeliveryEvidence(
            NOT_DISCHARGED,
            reason=(
                "this item stores no deployment flow, and no succeeded run of "
                "its project to a persistent environment carries this merge"
            ),
            recovery=(
                "Deliver this merge through a run of this project to a "
                "persistent environment; any flow's run counts."
            ),
        )
    if member is None:
        return DeliveryEvidence(
            NOT_DISCHARGED,
            reason="no succeeded release that ships this project contains this merge",
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
        release_lineage=str(member.get("release_lineage") or ""),
        project_id=member.get("project_id"),
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
