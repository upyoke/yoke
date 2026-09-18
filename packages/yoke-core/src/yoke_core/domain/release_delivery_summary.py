"""How many of a releasing item's merges have actually shipped.

An item waiting at its release stage has landed at least one merge and is
waiting for a run to carry it. "How many, and how many are out?" is the
question its card asks, and both halves come from records the control plane
already keeps.

The merges themselves are the landings the item recorded — each landing
writes a ``merge_queue_batch`` block naming the commit it merged, which
outlives the Actions window that produced it. Reading those is what lets a
merge that landed *after* the last run still be counted, and counted as not
deployed, which is the state the line exists to surface.

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
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.qa_merging_identity import recorded_batch_blocks

SUCCEEDED = "succeeded"


@dataclass(frozen=True)
class DeliverySummary:
    """One releasing item's merge counts."""

    merges: int = 0
    deployed: int = 0

    @property
    def not_deployed(self) -> int:
        return max(self.merges - self.deployed, 0)


def recorded_merge_shas(conn: Any, item_id: int) -> tuple[str, ...]:
    """Every distinct commit this item's own landings recorded, newest first."""
    seen: list[str] = []
    for block in recorded_batch_blocks(conn, int(item_id)):
        sha = str(block.get("merge_sha") or "").strip()
        if sha and sha not in seen:
            seen.append(sha)
    return tuple(seen)


def _carried_shas(raw: Any) -> set[str]:
    payload = loads_text(str(raw or "{}"))
    if not isinstance(payload, dict):
        return set()
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
    """Succeeded runs this project shipped to ``environment_id``, newest first.

    Ordered by completion with the empty string sorting last, which every
    backend agrees on — a run missing its completion is the oldest thing
    here, not the newest.
    """
    if environment_id is None:
        return []
    marker = _placeholder(conn)
    return query_rows(
        conn,
        "SELECT id, release_lineage, carried_work FROM deployment_runs "
        f"WHERE project_id={marker} AND target_environment_id={marker} "
        f"AND status={marker} "
        "ORDER BY COALESCE(completed_at, '') DESC, id DESC",
        (int(project_id), environment_id, SUCCEEDED),
    )


def delivery_summary(
    conn: Any, *, item_id: int, project_id: int, environment_id: Any
) -> DeliverySummary:
    """Count this item's landed merges and how many have shipped."""
    merges = recorded_merge_shas(conn, item_id)
    if not merges:
        return DeliverySummary()
    runs = succeeded_runs_for_environment(
        conn, project_id=project_id, environment_id=environment_id
    )
    carried: set[str] = set()
    for run in runs:
        carried |= _carried_shas(run.get("carried_work"))
    # Releases advance, so a commit an older release contained is contained
    # by the newest one too. Asking every lineage would spend one repository
    # resolution per run to re-derive an answer the first one already gives.
    newest_lineage = next(
        (
            str(run.get("release_lineage") or "").strip()
            for run in runs
            if str(run.get("release_lineage") or "").strip()
        ),
        "",
    )
    deployed = 0
    for sha in merges:
        if sha in carried:
            deployed += 1
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
    return DeliverySummary(merges=len(merges), deployed=deployed)


__all__ = [
    "DeliverySummary",
    "delivery_summary",
    "recorded_merge_shas",
    "succeeded_runs_for_environment",
]
