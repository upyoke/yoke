"""How many of an item's merges have actually shipped.

"How many landed, and how many are out?" is the question every Frontier card
that draws a delivery box asks — an item waiting at its release stage for a
run to carry it, and one already finished whose card names where the work
went. Both halves of the answer come from records the control plane already
keeps.

The merges themselves are the landings the item recorded, in either of the
two forms a landing takes. A merge queue writes a ``merge_queue_batch`` block
naming the commit it merged, which outlives the Actions window that produced
it. A standalone merge has no train to validate and writes no block at all —
its landing lives on the item's own merge receipt. Reading both is what lets
a merge that landed *after* the last run still be counted, and counted as not
deployed, which is the state the line exists to surface; reading only the
block made every project that merges without a queue look as though it had
never merged.

Which releases may be asked at all depends on what the item stores. One with
a selected flow is asked about the releases that reached that flow's
environment. One that stores no flow has no environment to name, so it stands
on the candidates the delivery-evidence ladder already walks for it — its own
project's releases to a destination that outlives the run — and the release
that carried the merge is also what the card names where a stored flow would
otherwise go.

Deployment is then one question per merge, asked two ways because a merge
reaches a release by two routes. Usually the run that carried it names it in
its own carried work. But a merge can also reach the base branch under
another item's landing, in which case no run ever lists it for this item
while it is nonetheless deployed. Ancestry answers that second case, through
the same containment helper the completion gate uses.

Only the newest release lineage is asked. Releases advance, so a commit an
older one contained is contained by the newest as well, and the answer is
the same either way — while asking each run in turn would spend a repository
resolution per run, on every load of a roster that draws many such items.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_run_candidate_containment import (
    candidate_contains_commit,
)
from yoke_core.domain.deployment_run_project_sources import (
    carrying_runs_for_project,
    environment_name,
)
from yoke_core.domain.delivery_release_candidates import (
    succeeded_persistent_runs,
)
from yoke_core.domain.item_merge_receipt_document import (
    merge_shas as receipt_merge_shas,
)
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.qa_merging_identity import recorded_batch_blocks

SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class DeliverySummary:
    """One item's merge counts, and the flow that shipped them.

    ``flow`` is the flow of the release that carried one of these merges. An
    item storing its own flow already knows it; one storing none has no other
    way to say where the work went, and reporting the absence of that stored
    field as the absence of a delivery is what this answers instead.
    """

    merges: int = 0
    deployed: int = 0
    flow: str = ""

    @property
    def not_deployed(self) -> int:
        return max(self.merges - self.deployed, 0)


def recorded_merge_shas(conn: Any, item_id: int) -> tuple[str, ...]:
    """Every distinct commit this item's own landings recorded, newest first.

    A queue landing's batch block and a standalone landing's merge receipt
    are the same fact written by the two routes to the base branch, so both
    are read and the same commit written by both counts once.
    """
    seen: list[str] = []
    recorded = [
        str(block.get("merge_sha") or "").strip()
        for block in recorded_batch_blocks(conn, int(item_id))
    ]
    recorded.extend(receipt_merge_shas(conn, int(item_id)))
    for sha in recorded:
        if sha and sha not in seen:
            seen.append(sha)
    return tuple(seen)


def _carried_shas(raw: Any, *, bound_project_id: int | None = None) -> set[str]:
    """The commits one run named for a project, its own or one it bound.

    A carrier records each bound project's carried set beside its own, so a
    bound project reads its own slice of the same record rather than the
    carrier's items, which belong to a different repository entirely.
    """
    payload = loads_text(str(raw or "{}"))
    if not isinstance(payload, dict):
        return set()
    if bound_project_id is not None:
        payload = next(
            (
                entry
                for entry in payload.get("bound_projects") or []
                if isinstance(entry, dict)
                and entry.get("project_id") == bound_project_id
            ),
            {},
        )
    carried: set[str] = set()
    for entry in payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        for sha in entry.get("commit_shas") or []:
            text = str(sha or "").strip()
            if text:
                carried.add(text)
    return carried


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def succeeded_runs_for_environment(
    conn: Any, *, project_id: int, environment_id: Any
) -> list[dict[str, Any]]:
    """Succeeded releases that shipped this project here, newest first.

    Its own runs to ``environment_id``, plus the runs of another project
    that bound this project's source and shipped it to an environment of the
    same name — the name a binding stage already passes through to the bound
    project's own release, so the two sides of one release line match up
    without either project naming the other.

    Ordered by completion with the empty string sorting last, which every
    backend agrees on — a run missing its completion is the oldest thing
    here, not the newest.
    """
    if environment_id is None:
        return []
    marker = _placeholder(conn)
    runs = query_rows(
        conn,
        "SELECT id, release_lineage, carried_work, COALESCE(flow, '') AS flow, "
        "COALESCE(completed_at, '') AS completed_at FROM deployment_runs "
        f"WHERE project_id={marker} AND target_environment_id={marker} "
        f"AND status={marker} "
        "ORDER BY COALESCE(completed_at, '') DESC, id DESC",
        (int(project_id), environment_id, SUCCEEDED),
    )
    runs.extend(
        {
            "id": run["id"],
            "release_lineage": run["source_sha"],
            "carried_work": run["carried_work"],
            "flow": run["flow"],
            # The carrier answers for several projects, so the reader has to
            # be told which slice of its record is this project's.
            "bound_project_id": int(project_id),
            "completed_at": run["completed_at"],
        }
        for run in carrying_runs_for_project(
            conn,
            int(project_id),
            environment_name=environment_name(conn, environment_id),
        )
    )
    runs.sort(key=lambda run: str(run.get("completed_at") or ""), reverse=True)
    return runs


def candidate_runs(
    conn: Any, *, project_id: int, environment_id: Any, flow: str
) -> list[dict[str, Any]]:
    """The succeeded releases this item's merges may be asked about.

    A stored flow names the environment to ask about. No stored flow names
    nothing, so the item stands on the candidates the delivery-evidence
    ladder already walks for it rather than being told it has no delivery.
    """
    if flow:
        return succeeded_runs_for_environment(
            conn, project_id=project_id, environment_id=environment_id
        )
    return succeeded_persistent_runs(conn, project_id=int(project_id))


def _carried_by_flow(runs: list[dict[str, Any]]) -> dict[str, str]:
    """Each commit these releases carried, against the flow that shipped it.

    Newest first, so a commit shipped more than once is named by the most
    recent release that carried it.
    """
    carried: dict[str, str] = {}
    for run in runs:
        for sha in _carried_shas(
            run.get("carried_work"),
            bound_project_id=run.get("bound_project_id"),
        ):
            carried.setdefault(sha, str(run.get("flow") or ""))
    return carried


def delivery_summary(
    conn: Any,
    *,
    item_id: int,
    project_id: int,
    environment_id: Any,
    flow: str = "",
) -> DeliverySummary:
    """Count this item's landed merges, how many shipped, and under which flow."""
    merges = recorded_merge_shas(conn, item_id)
    if not merges:
        return DeliverySummary()
    runs = candidate_runs(
        conn,
        project_id=project_id,
        environment_id=environment_id,
        flow=flow,
    )
    carried = _carried_by_flow(runs)
    # Releases advance, so a commit an older release contained is contained
    # by the newest one too. Asking every lineage would spend one repository
    # resolution per run to re-derive an answer the first one already gives.
    newest = next(
        (run for run in runs if str(run.get("release_lineage") or "").strip()),
        {},
    )
    newest_lineage = str(newest.get("release_lineage") or "").strip()
    deployed = 0
    carrying_flow = ""
    for sha in merges:
        if sha in carried:
            deployed += 1
            carrying_flow = carrying_flow or carried[sha]
            continue
        # Not named by any run: it may still have reached the base branch
        # under another item's landing, which ancestry — not carried work —
        # is the record of.
        if newest_lineage and candidate_contains_commit(
            conn,
            int(project_id),
            candidate_lineage=newest_lineage,
            commit_sha=sha,
        ).contained:
            deployed += 1
            carrying_flow = carrying_flow or str(newest.get("flow") or "")
    return DeliverySummary(
        merges=len(merges), deployed=deployed, flow=carrying_flow
    )


__all__ = [
    "DeliverySummary",
    "candidate_runs",
    "delivery_summary",
    "recorded_merge_shas",
    "succeeded_runs_for_environment",
]
