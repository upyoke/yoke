"""Candidate landings still being delivered by overview deployment runs.

Containment is a fact about code, not a new delivery on every later run.
Keep the first successful run for each landing and environment, plus runs
attempting a landing that has no success there yet. Membership is separate
and is never filtered by this projection.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_bound_sources import parse_bound_sources
from yoke_core.domain.deployment_run_contained_items import parse_candidate_containment
from yoke_core.domain.deployment_run_membership_removals import parse_membership_removals
from yoke_core.domain.hosted_promotion_receipt import PROMOTION_RECEIPTS_KEY
from yoke_core.domain.schema_common import _column_exists


Landing = tuple[int, int, str]
DeliveryKey = tuple[str, int, int, str]


def hosted_build_promoted(run: Mapping[str, Any]) -> bool:
    """An executing run has recorded promotion of its build to its target."""
    environment = run.get("target_environment")
    lineage = run.get("release_lineage")
    if run.get("status") != "executing" or not environment or not lineage:
        return False
    sources = parse_bound_sources(run.get("bound_sources"))
    return any(
        payload.get("target_environment") == environment
        and payload.get("product_sha") == lineage
        for source in sources["projects"] or ()
        for receipt in source.get(PROMOTION_RECEIPTS_KEY) or ()
        if (payload := receipt.get("payload"))
    )


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
    candidates = {str(run["id"]): _contained_landings(run) for run in runs}
    environments = sorted(
        {
            str(run.get("target_environment") or "")
            for run in runs
            if candidates[str(run["id"])]
        }
        - {""}
    )
    identities = {
        (int(item["project_id"]), int(item["id"]), str(item["merge_sha"]))
        for entries in candidates.values()
        for item in entries
    }
    first_success = _first_successful_landings(conn, identities, environments)
    visible: dict[str, list[dict[str, int | str]]] = {}
    for run in runs:
        run_id = str(run["id"])
        environment = str(run.get("target_environment") or "")
        visible[run_id] = [
            {"id": int(item["id"]), "project_id": int(item["project_id"])}
            for item in candidates[run_id]
            if not (
                delivered_by := first_success.get(
                    (
                        environment,
                        int(item["project_id"]),
                        int(item["id"]),
                        str(item["merge_sha"]),
                    )
                )
            )
            or (run.get("status") == "succeeded" and delivered_by["id"] == run_id)
        ]
    return visible


def _first_successful_landings(
    conn: Any,
    identities: set[Landing],
    environments: list[str] | None = None,
) -> dict[DeliveryKey, Mapping[str, Any]]:
    if (
        not identities
        or environments == []
        or not _column_exists(conn, "deployment_runs", "candidate_containment")
        or not _column_exists(conn, "deployment_runs", "target_environment_id")
    ):
        return {}

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    environment_filter = ""
    if environments:
        holes = ", ".join(marker for _ in environments)
        environment_filter = f" AND e.name IN ({holes})"
    if db_backend.connection_is_postgres(conn):
        answers = "jsonb_array_elements(NULLIF(dr.candidate_containment, '')::jsonb->'answers') a"
        project = "CAST(a.value->>'project_id' AS BIGINT)"
        item = "CAST(a.value->>'id' AS BIGINT)"
        sha = "a.value->>'merge_sha'"
        state = "a.value->>'state'"
    else:
        answers = "json_each(dr.candidate_containment, '$.answers') a"
        project = "CAST(json_extract(a.value, '$.project_id') AS INTEGER)"
        item = "CAST(json_extract(a.value, '$.id') AS INTEGER)"
        sha = "json_extract(a.value, '$.merge_sha')"
        state = "json_extract(a.value, '$.state')"
    values = ",".join(f"({marker},{marker},{marker})" for _ in identities)
    succeeded = conn.execute(
        f"WITH wanted(project_id,item_id,merge_sha) AS (VALUES {values}), "
        "ranked AS (SELECT dr.id,dr.project_id AS run_project_id,e.name AS target_environment,"
        "w.project_id,w.item_id,w.merge_sha,dr.created_at,"
        "ROW_NUMBER() OVER (PARTITION BY e.name,w.project_id,w.item_id,w.merge_sha "
        "ORDER BY dr.completed_at NULLS LAST,dr.id) AS ordinal "
        "FROM deployment_runs dr "
        "JOIN environments e ON e.id=dr.target_environment_id "
        f"JOIN {answers} ON TRUE JOIN wanted w ON "
        f"w.project_id={project} AND w.item_id={item} AND w.merge_sha={sha} "
        f"WHERE dr.status='succeeded' AND {state}='contained'{environment_filter}) "
        "SELECT * FROM ranked WHERE ordinal=1 "
        "ORDER BY created_at DESC NULLS LAST,id DESC",
        (
            *(value for identity in sorted(identities) for value in identity),
            *(environments or ()),
        ),
    ).fetchall()
    return {
        (
            str(row["target_environment"]),
            int(row["project_id"]),
            int(row["item_id"]),
            str(row["merge_sha"]),
        ): row
        for row in succeeded
    }


def first_carried_builds(
    conn: Any,
    landings: set[Landing],
    *,
    readable_project_ids: set[int] | None,
) -> dict[int, list[dict[str, str | int]]]:
    """Link visible cards to first successful carried runs outside the roster."""
    from yoke_core.domain.deployment_run_member_presentation import _member_items

    successes = _first_successful_landings(conn, landings)
    readable = [
        row for row in successes.values()
        if readable_project_ids is None or int(row["run_project_id"]) in readable_project_ids
    ]
    if not readable:
        return {}
    run_ids = sorted({str(row["id"]) for row in readable})
    members = {
        (run_id, int(item["id"]))
        for run_id, items in _member_items(conn, run_ids).items()
        for item in items
    }
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    marks = ", ".join(marker for _ in run_ids)
    removed = {
        (str(row["id"]), int(entry["item_id"]))
        for row in conn.execute(
            f"SELECT id, membership_removals FROM deployment_runs WHERE id IN ({marks})",
            tuple(run_ids),
        ).fetchall()
        for entry in parse_membership_removals(row["membership_removals"], str(row["id"]))
    }
    result: dict[int, list[dict[str, str | int]]] = {}
    seen: set[tuple[int, str]] = set()
    for row in readable:
        run_id, item_id = str(row["id"]), int(row["item_id"])
        environment = str(row["target_environment"])
        key = item_id, environment
        if key in seen:
            continue
        seen.add(key)
        if (run_id, item_id) in members or (run_id, item_id) in removed:
            continue
        result.setdefault(item_id, []).append({
            "id": run_id,
            "project_id": int(row["run_project_id"]),
            "target_environment": environment,
        })
    return result


__all__ = ["candidate_delivery_items", "first_carried_builds", "hosted_build_promoted"]
