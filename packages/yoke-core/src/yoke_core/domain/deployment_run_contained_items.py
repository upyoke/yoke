"""Persist the item-card containment snapshot when a run starts.

Membership names delivery custody.  A stage flow that takes no custody still
needs to appear on the cards for the merges its pinned candidate contains,
but that answer must not perform repository I/O on every list request.  This
module derives the answer once at the created-to-executing boundary and stores
the result on the run.  Readers only parse that record.
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
    UNDETERMINED,
    CandidateContainment,
)
from yoke_core.domain.deployment_run_project_sources import recorded_source_sha
from yoke_core.domain.item_finished_times import finished_times_in_window
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.release_delivery_summary import recorded_merge_shas_for_items
from yoke_core.domain.schema_common import _column_exists


CANDIDATE_CONTAINMENT_FIELD = "candidate_containment"
CANDIDATE_CONTAINMENT_SCHEMA = 1


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def parse_candidate_containment(value: Any) -> dict[str, Any]:
    """Return the stored snapshot, or an explicit not-recorded result."""
    empty = {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "derivation": {
            "status": "not_recorded",
            "contents_known": False,
            "reason": "candidate_containment_not_recorded",
        },
        "items": [],
    }
    if value in (None, ""):
        return empty
    payload = dict(value) if isinstance(value, Mapping) else None
    if payload is None:
        try:
            parsed = loads_text(str(value))
        except (TypeError, ValueError):
            return empty
        payload = dict(parsed) if isinstance(parsed, Mapping) else None
    if payload is None:
        return empty
    payload.setdefault("schema", CANDIDATE_CONTAINMENT_SCHEMA)
    payload.setdefault("derivation", empty["derivation"])
    payload.setdefault("items", [])
    return payload


def _carried_project_ids(run: Mapping[str, Any]) -> tuple[int, ...]:
    project_id = int(run["project_id"])
    payload = parse_bound_sources(run.get(BOUND_SOURCES_FIELD))
    bound = [pid for pid in bound_project_shas(payload) if pid != project_id]
    return (project_id, *sorted(bound))


def _visibility_item_ids(conn: Any, project_id: int) -> tuple[int, ...]:
    """Items a live delivery box could name: open, or finished today."""
    found = {int(record["id"]) for record in merged_open_items(conn, project_id)}
    finished = finished_times_in_window(conn)
    if finished:
        ids = sorted(finished)
        marker = _p(conn)
        holes = ", ".join(marker for _ in ids)
        rows = query_rows(
            conn,
            f"SELECT id FROM items WHERE project_id={marker} AND id IN ({holes})",
            (int(project_id), *ids),
        )
        found.update(int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows)
    return tuple(sorted(found))


def derive_candidate_containment(conn: Any, run: Mapping[str, Any]) -> dict[str, Any]:
    """Derive one immutable containment snapshot for *run*."""
    items: list[dict[str, int]] = []
    refusals: dict[str, str] = {}
    for project_id in _carried_project_ids(run):
        lineage = recorded_source_sha(run, project_id)
        item_ids = _visibility_item_ids(conn, project_id)
        merges = recorded_merge_shas_for_items(conn, item_ids)
        containment = CandidateContainment(
            conn,
            project_id,
            candidate_lineage=lineage,
        )
        for item_id in item_ids:
            shas = merges.get(item_id) or ()
            if not shas:
                continue
            verdict = containment.contains(shas[0])
            if verdict.contained:
                items.append({"id": item_id, "project_id": project_id})
            elif verdict.state == UNDETERMINED:
                refusals.setdefault(verdict.reason, verdict.recovery)
    items.sort(key=lambda item: item["id"])
    known = not refusals
    derivation: dict[str, Any] = {
        "status": "known" if known else "partial" if items else "unknown",
        "contents_known": known,
    }
    if refusals:
        derivation["reason"] = ", ".join(refusals)
        derivation["recovery"] = " ".join(
            recovery for recovery in refusals.values() if recovery
        )
    return {
        "schema": CANDIDATE_CONTAINMENT_SCHEMA,
        "derivation": derivation,
        "items": items,
    }


def record_candidate_containment(conn: Any, run_id: str) -> dict[str, Any]:
    """Persist the run's containment once and return the stored snapshot."""
    if not _column_exists(conn, "deployment_runs", CANDIDATE_CONTAINMENT_FIELD):
        raise RuntimeError(
            "candidate_containment_schema_unconverged: deployment_runs."
            "candidate_containment is missing; boot the current build to apply "
            "its additive schema, then start the run again"
        )
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id,release_lineage,bound_sources,"
        f"{CANDIDATE_CONTAINMENT_FIELD} FROM deployment_runs WHERE id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    stored = _cell(row, CANDIDATE_CONTAINMENT_FIELD, 3)
    if stored not in (None, ""):
        return parse_candidate_containment(stored)
    run = {
        "project_id": int(_cell(row, "project_id", 0)),
        "release_lineage": _cell(row, "release_lineage", 1),
        "bound_sources": _cell(row, "bound_sources", 2),
    }
    snapshot = derive_candidate_containment(conn, run)
    conn.execute(
        f"UPDATE deployment_runs SET {CANDIDATE_CONTAINMENT_FIELD}={marker} "
        f"WHERE id={marker}",
        (dumps_compact(snapshot), run_id),
    )
    return snapshot


__all__ = [
    "CANDIDATE_CONTAINMENT_FIELD",
    "derive_candidate_containment",
    "parse_candidate_containment",
    "record_candidate_containment",
]
