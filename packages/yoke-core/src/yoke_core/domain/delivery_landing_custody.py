"""Which deployment run, if any, holds one item's current landing.

Two questions share this answer, and they were drifting apart. Enrollment has
to know whether a merged, delivery-ready item still needs a release to take
it. The steering report has to say whether a landed item is being delivered or
is stranded with nobody carrying it. Asking that twice in two places is how one
of them ends up right and the other quietly wrong.

Custody belongs to a LANDING, not to an item
--------------------------------------------
An item can land more than once, and its landings can straddle releases: a run
may carry the first merge while a later merge sits in no run at all. So the
question asked here is always "who holds THIS commit", and the item is only
ever the way its current commit is found.

That makes custody a conjunction of two facts that are each insufficient:

* **Membership** is who OWES the item its delivery and its post-deploy proof.
  Alone it over-answers — a membership in a run whose lineage predates a newer
  merge says nothing about that merge.
* **Containment** is whether a run's pinned candidate actually CARRIES this
  commit. Alone it over-answers in the opposite direction — every release cut
  after a merge contains it, including releases that never owed the item
  anything. That reading is what made the stranded items invisible: a later
  run carried their code, so every code-shaped question said "delivered" while
  no run had ever taken responsibility for them.

A run holds a landing only when both hold, and only while the run is live or
succeeded. A failed or cancelled run holds nothing — its ending releases its
members, which is precisely the hole a cancelled run used to leave open.

An unanswerable containment is its own verdict
----------------------------------------------
:data:`UNDETERMINED` is never collapsed into either answer. A caller that
could not compare commits has not learned that a release carries this merge,
nor that none does. Enrollment admits nothing on it and the report names it,
because a guess in either direction is a silent wrong delivery decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.deployment_run_candidate_containment import (
    UNDETERMINED as CONTAINMENT_UNDETERMINED,
    candidate_contains_commit,
)
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_sources_recorded,
)
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.runs import ACTIVE_RUN_STATUSES, RunStatus
from yoke_core.domain.schema_common import _column_exists, _table_exists


#: A live or succeeded member run's candidate carries this landing. The
#: delivery is either coming or already happened, and it is owed by a run
#: that named the item.
HELD = "held"
#: The item has live or succeeded member runs, but none of their candidates
#: carries this landing: it merged again after the run that holds it. The
#: newest such run is named so the reader can see what it is behind.
REMERGED = "remerged"
#: No live or succeeded run names this item at all. Nothing owes it a
#: delivery, whatever some release's candidate happens to contain.
UNHELD = "unheld"
#: Containment could not be compared on this host. Neither answer is known.
UNDETERMINED = "undetermined"

#: The run statuses that can hold a landing: still composing or executing,
#: so the delivery is coming, or succeeded, so it already happened. Failed
#: and cancelled runs release their members by ending.
HOLDING_RUN_STATUSES = frozenset(ACTIVE_RUN_STATUSES | {RunStatus.SUCCEEDED.value})

#: The states a run start may still enroll. ``HELD`` is already someone's
#: obligation and ``UNDETERMINED`` is not a fact to act on.
ENROLLABLE_CUSTODY_STATES = frozenset({REMERGED, UNHELD})

#: Where a landing stamp may be recorded. The earlier present one is the
#: moment the code reached the base branch.
LANDING_STAMP_COLUMNS = ("merged_at", "merge_queue_landed_at")


@dataclass(frozen=True)
class LandingCustody:
    """Who holds one item's current landing, and on what evidence."""

    item_id: int
    #: The commit this item's newest landing receipt names, or ``""``.
    landing_sha: str
    state: str
    #: The run the state is about: the holder for :data:`HELD`, the newest
    #: run left behind for :data:`REMERGED`, empty otherwise.
    run_id: str = ""
    run_status: str = ""
    #: Why containment could not answer, for :data:`UNDETERMINED` only.
    reason: str = ""
    recovery: str = ""

    @property
    def held(self) -> bool:
        return self.state == HELD

    @property
    def enrollable(self) -> bool:
        """Whether a run start may take this landing on."""
        return self.state in ENROLLABLE_CUSTODY_STATES


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _bound_sources_column(conn: Any) -> str:
    """Name the stored bound-source record, or a constant before converge.

    The column arrives on a boot converge this very code may be driving, so
    the read cannot assume it and cannot refuse without it.
    """
    if bound_sources_recorded(conn):
        return f"COALESCE(dr.{BOUND_SOURCES_FIELD},'')"
    return "''"


def landing_stamp_columns(conn: Any) -> tuple[str, ...]:
    """The landing stamps this database actually has.

    ``merge_queue_landed_at`` arrives with the merge-queue schema, so a
    control plane that has not converged it still answers the question from
    ``merged_at`` alone rather than failing the whole read.
    """
    return tuple(
        column
        for column in LANDING_STAMP_COLUMNS
        if _column_exists(conn, "items", column)
    )


def merged_open_items(conn: Any, project_id: int) -> tuple[dict[str, Any], ...]:
    """This project's items that landed and never reached a terminal status.

    The one definition of "merged but still open", shared by the steering
    report's landed section and by run enrollment, so the two can never
    disagree about which items are even in the conversation.
    """
    columns = landing_stamp_columns(conn)
    if not columns:
        return ()
    marker = _p(conn)
    terminal = sorted(TERMINAL_STATUSES)
    holes = ", ".join(marker for _ in terminal)
    present = " OR ".join(f"{column} IS NOT NULL" for column in columns)
    rows = conn.execute(
        f"SELECT id, status, {', '.join(columns)} FROM items "
        f"WHERE project_id = {marker} AND status NOT IN ({holes}) "
        f"AND ({present})",
        (int(project_id), *terminal),
    ).fetchall()
    return tuple(dict(row) for row in rows)


def landed_at(record: Mapping[str, Any]) -> str:
    """The earliest recorded landing stamp on one item row, or ``""``."""
    present = [
        str(record.get(column) or "")
        for column in LANDING_STAMP_COLUMNS
        if record.get(column)
    ]
    return min(present) if present else ""


def _member_runs(conn: Any, item_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    """Each item's live and succeeded member runs, newest membership first."""
    if not item_ids:
        return {}
    if not all(
        _table_exists(conn, table)
        for table in ("deployment_runs", "deployment_run_items")
    ):
        return {}
    marker = _p(conn)
    statuses = sorted(HOLDING_RUN_STATUSES)
    item_holes = ", ".join(marker for _ in item_ids)
    status_holes = ", ".join(marker for _ in statuses)
    rows = conn.execute(
        f"SELECT dri.item_id AS item_id, dr.id AS run_id, dr.status AS status, "
        f"dr.project_id AS project_id, "
        f"COALESCE(dr.release_lineage,'') AS release_lineage, "
        f"{_bound_sources_column(conn)} AS {BOUND_SOURCES_FIELD} "
        f"FROM deployment_run_items dri "
        f"JOIN deployment_runs dr ON dr.id = dri.run_id "
        f"WHERE dri.item_id IN ({item_holes}) AND dr.status IN ({status_holes}) "
        f"ORDER BY dri.added_at DESC, dr.id DESC",
        (*(int(value) for value in item_ids), *statuses),
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        record = dict(row)
        grouped.setdefault(int(record["item_id"]), []).append(record)
    return grouped


def _landing_shas(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity

    return {
        int(item_id): item_merge_identity(conn, int(item_id))
        for item_id in item_ids
    }


def _custody_for(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    landing_sha: str,
    runs: Sequence[Mapping[str, Any]],
) -> LandingCustody:
    """Walk one item's member runs for the first that carries this landing."""
    if not runs:
        return LandingCustody(item_id=item_id, landing_sha=landing_sha, state=UNHELD)
    if not landing_sha:
        # A member run with no landing identity to compare cannot be shown to
        # carry this merge or to have been overtaken by it. Saying "unheld"
        # would re-enroll an item a run is actively delivering.
        newest = dict(runs[0])
        return LandingCustody(
            item_id=item_id,
            landing_sha="",
            state=UNDETERMINED,
            run_id=str(newest["run_id"]),
            run_status=str(newest["status"]),
            reason="this item records no landing commit to compare",
            recovery=(
                "Record the item's merge identity through its close-out, then "
                "retry."
            ),
        )
    undetermined: LandingCustody | None = None
    for run in runs:
        lineage = recorded_source_sha(dict(run), int(project_id))
        if not lineage:
            continue
        verdict = candidate_contains_commit(
            conn,
            int(project_id),
            candidate_lineage=lineage,
            commit_sha=landing_sha,
        )
        if verdict.contained:
            return LandingCustody(
                item_id=item_id,
                landing_sha=landing_sha,
                state=HELD,
                run_id=str(run["run_id"]),
                run_status=str(run["status"]),
            )
        if verdict.state == CONTAINMENT_UNDETERMINED and undetermined is None:
            # Keep walking: an older member run may still answer, and a
            # definite yes beats an unreadable maybe.
            undetermined = LandingCustody(
                item_id=item_id,
                landing_sha=landing_sha,
                state=UNDETERMINED,
                run_id=str(run["run_id"]),
                run_status=str(run["status"]),
                reason=verdict.reason,
                recovery=verdict.recovery,
            )
    if undetermined is not None:
        return undetermined
    newest = dict(runs[0])
    return LandingCustody(
        item_id=item_id,
        landing_sha=landing_sha,
        state=REMERGED,
        run_id=str(newest["run_id"]),
        run_status=str(newest["status"]),
    )


def landing_custody(
    conn: Any, *, project_id: int, item_ids: Sequence[int]
) -> dict[int, LandingCustody]:
    """Answer custody for every one of ``item_ids`` in one pass.

    Batched because both callers ask about a whole project's landed items at
    once, and the membership read is the part worth doing once. Containment
    is still asked per item: it is a comparison against that item's own
    commit, and there is no cheaper shape for it.
    """
    ids = [int(value) for value in item_ids]
    if not ids:
        return {}
    runs = _member_runs(conn, ids)
    shas = _landing_shas(conn, ids)
    return {
        item_id: _custody_for(
            conn,
            item_id=item_id,
            project_id=int(project_id),
            landing_sha=shas.get(item_id, ""),
            runs=runs.get(item_id, ()),
        )
        for item_id in ids
    }


__all__ = [
    "ENROLLABLE_CUSTODY_STATES",
    "HELD",
    "HOLDING_RUN_STATUSES",
    "LANDING_STAMP_COLUMNS",
    "LandingCustody",
    "REMERGED",
    "UNDETERMINED",
    "UNHELD",
    "landed_at",
    "landing_custody",
    "landing_stamp_columns",
    "merged_open_items",
]
