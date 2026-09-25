"""Candidate landings still being delivered by overview deployment runs.

Containment is a fact about code, not a new delivery on every later run.
Keep the first successful run for each landing and environment, plus runs
attempting a landing that has no success there yet. Membership is separate
and is never filtered by this projection.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_contained_items import parse_candidate_containment
from yoke_core.domain.schema_common import _column_exists


def _contained_landings(run: Mapping[str, Any]) -> list[dict[str, int | str]]:
    snapshot = parse_candidate_containment(run.get("candidate_containment"))
    return [
        {
            "id": int(answer["id"]),
            "project_id": int(answer["project_id"]),
            "merge_sha": str(answer["merge_sha"]),
        }
        for answer in snapshot.get("answers") or ()
        if answer.get("state") == "contained"
        and answer.get("id") is not None
        and answer.get("project_id") is not None
        and answer.get("merge_sha")
    ]


def candidate_delivery_items(
    conn: Any, runs: list[dict[str, Any]]
) -> dict[str, list[dict[str, int | str]]]:
    """Return candidate items owed by each run, keyed by run id.

    A successful run counts for the exact landing in its recorded snapshot,
    in its target environment. Other environments and a newer landing are
    independent. A failed run never satisfies delivery, so its retry remains
    visible until a run succeeds.
    """
    candidates = {
        str(run["id"]): _contained_landings(run)
        for run in runs
    }
    environments = sorted({
        str(run.get("target_environment") or "")
        for run in runs if candidates[str(run["id"])]
    } - {""})
    if (not environments
            or not _column_exists(conn, "deployment_runs", "candidate_containment")
            or not _column_exists(conn, "deployment_runs", "target_environment_id")):
        return candidates

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    holes = ", ".join(marker for _ in environments)
    succeeded = conn.execute(
        "SELECT dr.id, dr.candidate_containment, e.name AS target_environment "
        "FROM deployment_runs dr "
        "JOIN environments e ON e.id = dr.target_environment_id "
        f"WHERE dr.status={marker} AND e.name IN ({holes}) "
        "AND dr.candidate_containment IS NOT NULL "
        "ORDER BY dr.completed_at, dr.id",
        ("succeeded", *environments),
    ).fetchall()
    first_success: dict[tuple[str, int, int, str], str] = {}
    for row in succeeded:
        record = dict(row)
        environment = str(record["target_environment"])
        for item in _contained_landings(record):
            key = (
                environment, int(item["project_id"]), int(item["id"]),
                str(item["merge_sha"]),
            )
            first_success.setdefault(key, str(record["id"]))

    visible: dict[str, list[dict[str, int | str]]] = {}
    for run in runs:
        run_id = str(run["id"])
        environment = str(run.get("target_environment") or "")
        visible[run_id] = [
            {"id": int(item["id"]), "project_id": int(item["project_id"])}
            for item in candidates[run_id]
            if not (delivered_by := first_success.get((
                environment, int(item["project_id"]), int(item["id"]),
                str(item["merge_sha"]),
            ))) or (run.get("status") == "succeeded" and delivered_by == run_id)
        ]
    return visible


__all__ = ["candidate_delivery_items"]
