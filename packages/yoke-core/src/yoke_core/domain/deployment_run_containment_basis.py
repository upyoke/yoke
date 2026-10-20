"""The source identities and merge questions a containment snapshot must answer."""

from __future__ import annotations
from hashlib import sha256
from typing import Any, Mapping
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_landing_guard import require_closed_landings
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.delivery_landing_custody import merged_open_items
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_project_shas,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.item_finished_times import finished_times_since
from yoke_core.domain.deployment_run_carried_work import previous_release_run
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists

CANDIDATE_CONTAINMENT_FIELD = "candidate_containment"
CANDIDATE_CONTAINMENT_SCHEMA = 1


def _p(conn):
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row, key, index):
    return row[key] if hasattr(row, "keys") else row[index]


def _carried_project_ids(run: Mapping[str, Any]) -> tuple[int, ...]:
    project_id = int(run["project_id"])
    payload = parse_bound_sources(run.get(BOUND_SOURCES_FIELD))
    bound = [pid for pid in bound_project_shas(payload) if pid != project_id]
    return (project_id, *sorted(bound))


def _delivery_item_ids(conn: Any, project_id: int, since) -> tuple[int, ...]:
    """Merged open items and finishers not covered by the preceding release."""
    marker = _p(conn)
    if (
        conn.execute(
            f"SELECT 1 FROM items WHERE project_id={marker} LIMIT 1", (project_id,)
        ).fetchone()
        is None
    ):
        return ()
    found = {int(record["id"]) for record in merged_open_items(conn, project_id)}
    finished = finished_times_since(conn, since)
    if finished:
        ids = sorted(finished)
        holes = ", ".join(marker for _ in ids)
        rows = query_rows(
            conn,
            f"SELECT id FROM items WHERE project_id={marker} AND id IN ({holes})",
            (int(project_id), *ids),
        )
        found.update(int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows)
    return tuple(sorted(found))


def _basis_digest(basis: Mapping[str, Any]) -> str:
    payload = {
        "schema": int(basis.get("schema") or CANDIDATE_CONTAINMENT_SCHEMA),
        "primary_project": str(basis.get("primary_project") or ""),
        "projects": list(basis.get("projects") or ()),
    }
    return sha256(dumps_compact(payload).encode("utf-8")).hexdigest()


def candidate_containment_basis(
    conn: Any, run_id: str, *, bound_sources: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return the server-owned questions a local checkout must answer."""
    recorded = _column_exists(conn, "deployment_runs", CANDIDATE_CONTAINMENT_FIELD)
    stored_column = CANDIDATE_CONTAINMENT_FIELD if recorded else "NULL"
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id,release_lineage,bound_sources,"
        f"{stored_column} AS {CANDIDATE_CONTAINMENT_FIELD},target_environment_id "
        f"FROM deployment_runs WHERE id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    stored = _cell(row, CANDIDATE_CONTAINMENT_FIELD, 3)
    if stored not in (None, "") and bound_sources is None:
        from yoke_core.domain.deployment_run_contained_items import (
            parse_candidate_containment,
        )

        snapshot = parse_candidate_containment(stored)
        require_closed_landings(
            conn,
            {
                int(item["id"])
                for item in [*snapshot.get("items", []), *snapshot.get("answers", [])]
            },
        )
        return {"schema": CANDIDATE_CONTAINMENT_SCHEMA, "recorded_snapshot": snapshot}
    run = {
        "project_id": int(_cell(row, "project_id", 0)),
        "release_lineage": _cell(row, "release_lineage", 1),
        "bound_sources": bound_sources
        if bound_sources is not None
        else _cell(row, "bound_sources", 2),
    }
    previous = previous_release_run(
        conn, run_id, run["project_id"], _cell(row, "target_environment_id", 4)
    )
    anchor = None
    if previous is not None:
        started = conn.execute(
            f"SELECT started_at FROM deployment_runs WHERE id={marker}",
            (_cell(previous, "id", 0),),
        ).fetchone()[0]
        anchor = parse_instant(started) if started is not None else None
    project_ids = _carried_project_ids(run)
    holes = ", ".join(marker for _ in project_ids)
    slug_rows = query_rows(
        conn,
        f"SELECT id,slug FROM projects WHERE id IN ({holes})",
        tuple(project_ids),
    )
    slugs = {int(row["id"]): str(row["slug"]) for row in slug_rows}
    projects: list[dict[str, Any]] = []
    for project_id in project_ids:
        item_ids = _delivery_item_ids(conn, project_id, anchor)
        require_closed_landings(conn, item_ids)
        merges = recorded_merge_shas_for_items(conn, item_ids)
        items = [
            {
                "id": item_id,
                "public_ref": render_item_ref(conn, item_id),
                "merge_sha": merges[item_id][0],
            }
            for item_id in item_ids
            if merges.get(item_id)
        ]
        projects.append(
            {
                "project_id": project_id,
                "project": slugs.get(project_id, ""),
                "candidate_lineage": recorded_source_sha(run, project_id),
                "items": items,
            }
        )
    basis = {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "primary_project": slugs.get(project_ids[0], ""),
        "projects": projects,
    }
    basis["basis_digest"] = _basis_digest(basis)
    return basis
