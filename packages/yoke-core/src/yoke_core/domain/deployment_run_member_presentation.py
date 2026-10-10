"""Active and removed release members for deployment-run cards."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.time_parse import parse_timestamp_utc
from yoke_core.domain.deployment_run_membership_removals import (
    parse_membership_removals,
)


def _member_items(
    conn: Any,
    run_ids: list[str],
    *,
    visible_project_ids: Optional[set[int]] = None,
) -> dict[str, list[dict[str, Any]]]:
    if not run_ids or visible_project_ids == set():
        return {}
    markers = ", ".join("%s" for _ in run_ids)
    visibility = ""
    params: list[Any] = list(run_ids)
    if visible_project_ids is not None:
        project_ids = sorted(visible_project_ids)
        visibility = (
            " AND i.project_id IN (" + ", ".join("%s" for _ in project_ids) + ")"
        )
        params.extend(project_ids)
    rows = conn.execute(
        "SELECT dri.run_id, i.id, i.title, i.status, i.project_sequence, "
        "p.id AS project_id, p.slug AS project, p.public_item_prefix "
        "FROM deployment_run_items dri "
        "JOIN items i ON i.id = dri.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE dri.run_id IN ({markers}){visibility} "
        "ORDER BY dri.run_id, i.id",
        tuple(params),
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item_id = int(row["id"])
        result.setdefault(str(row["run_id"]), []).append(
            {
                "id": item_id,
                "ref": format_item_ref(
                    str(row["project"]),
                    str(row["public_item_prefix"] or ""),
                    int(row["project_sequence"]),
                ),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "project_id": int(row["project_id"]),
                "project_sequence": int(row["project_sequence"]),
                "project": str(row["project"]),
            }
        )
    return result


def removed_member_items(
    conn: Any,
    runs: list[dict[str, Any]],
    *,
    visible_project_ids: Optional[set[int]] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Project existing removal decisions, with any newer release holding them."""
    removals = {
        str(run["id"]): parse_membership_removals(
            run.get("membership_removals"), str(run["id"])
        )
        for run in runs
    }
    item_ids = sorted(
        {int(entry["item_id"]) for entries in removals.values() for entry in entries}
    )
    if not item_ids or visible_project_ids == set():
        return {}
    markers = ", ".join("%s" for _ in item_ids)
    visibility = ""
    params: list[Any] = list(item_ids)
    if visible_project_ids is not None:
        project_ids = sorted(visible_project_ids)
        visibility = (
            " AND i.project_id IN (" + ", ".join("%s" for _ in project_ids) + ")"
        )
        params.extend(project_ids)
    rows = conn.execute(
        "SELECT i.id, i.title, i.project_sequence, i.project_id, "
        "p.slug AS project, p.public_item_prefix "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        f"WHERE i.id IN ({markers}){visibility}",
        tuple(params),
    ).fetchall()
    identities = {
        int(row["id"]): {
            "id": int(row["id"]),
            "title": str(row["title"]),
            "project_id": int(row["project_id"]),
            "project_sequence": int(row["project_sequence"]),
            "ref": format_item_ref(
                str(row["project"]),
                str(row["public_item_prefix"] or ""),
                int(row["project_sequence"]),
            ),
        }
        for row in rows
    }
    # Membership is durable custody. Failed/cancelled runs do not promise a ride.
    later = conn.execute(
        "SELECT dri.item_id, dr.id, dr.created_at FROM deployment_run_items dri "
        "JOIN deployment_runs dr ON dr.id=dri.run_id "
        f"WHERE dri.item_id IN ({markers}) AND dr.status NOT IN ('failed', 'cancelled') "
        "ORDER BY dr.created_at DESC, dr.id DESC",
        tuple(item_ids),
    ).fetchall()
    created = {
        str(run["id"]): parse_timestamp_utc(run.get("created_at")) for run in runs
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for run_id, entries in removals.items():
        for entry in entries:
            item_id = int(entry["item_id"])
            if item_id not in identities:
                continue
            next_run = next(
                (
                    str(row["id"])
                    for row in later
                    if int(row["item_id"]) == item_id
                    and str(row["id"]) != run_id
                    and created[run_id] is not None
                    and parse_instant(row["created_at"]) > created[run_id]
                ),
                None,
            )
            result.setdefault(run_id, []).append(
                {
                    **identities[item_id],
                    "reason": str(entry.get("reason") or ""),
                    "removed_at": (
                        format_instant(entry["removed_at"])
                        if entry.get("removed_at") is not None
                        else None
                    ),
                    "later_run_id": next_run,
                }
            )
    return result
