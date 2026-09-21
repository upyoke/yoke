"""In-flight runs the Frontier card can show without taking delivery custody.

Membership is who owes the item a delivery. A schema-v1 stage flow never
enrolls, so an executing stage run has no member rows and a card that
indexes only by membership draws nothing for it for the whole run. Honest
``carried_work`` is recorded at success, so it cannot name the live box
either.

This read answers the remaining question: which items' recorded merges does
this still-moving candidate already contain? The answer is a join key for
the box, never a ``deployment_run_items`` row and never a delivery count.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.delivery_landing_custody import merged_open_items
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_project_shas,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_candidate_containment import (
    CandidateContainment,
)
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.item_finished_times import finished_times_in_window
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _carried_project_ids(run: Mapping[str, Any]) -> tuple[int, ...]:
    own = run.get("project_id")
    if own in (None, ""):
        return ()
    project_id = int(own)
    payload = parse_bound_sources(
        run.get("bound_sources") if "bound_sources" in run
        else run.get(BOUND_SOURCES_FIELD)
    )
    bound = [
        pid for pid in bound_project_shas(payload) if pid != project_id
    ]
    return (project_id, *sorted(bound))


def _visibility_item_ids(conn: Any, project_id: int) -> tuple[int, ...]:
    """Items a delivery box could name for this project: open, or finished today."""
    found = {int(record["id"]) for record in merged_open_items(conn, project_id)}
    finished = finished_times_in_window(conn)
    if not finished:
        return tuple(sorted(found))
    ids = sorted(finished)
    marker = _p(conn)
    holes = ", ".join(marker for _ in ids)
    rows = query_rows(
        conn,
        f"SELECT id FROM items WHERE project_id={marker} AND id IN ({holes})",
        (int(project_id), *ids),
    )
    found.update(
        int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows
    )
    return tuple(sorted(found))


def live_visible_items(conn: Any, run: Mapping[str, Any]) -> list[dict[str, int]]:
    """Items whose newest recorded merge this in-flight candidate contains.

    Terminal runs are omitted: succeeded delivery is membership, honest
    carried work, or ancestry, and counting an in-flight containment as
    deployed would lie. A run with no project or no pinned lineage has
    nothing to compare.
    """
    if str(run.get("status") or "") in TERMINAL_RUN_STATUSES:
        return []
    visible: list[dict[str, int]] = []
    seen: set[int] = set()
    for project_id in _carried_project_ids(run):
        lineage = recorded_source_sha(run, project_id)
        if not lineage:
            continue
        item_ids = _visibility_item_ids(conn, project_id)
        if not item_ids:
            continue
        merges = recorded_merge_shas_for_items(conn, item_ids)
        containment = CandidateContainment(
            conn, project_id, candidate_lineage=lineage,
        )
        for item_id in item_ids:
            if item_id in seen:
                continue
            shas = merges.get(item_id) or ()
            if not shas:
                continue
            if not containment.contains(shas[0]).contained:
                continue
            seen.add(item_id)
            visible.append({"id": item_id})
    visible.sort(key=lambda item: item["id"])
    return visible


__all__ = ["live_visible_items"]
