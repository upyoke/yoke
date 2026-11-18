"""Computed membership and live carried work for one deployment-run read.

``deployment_runs.get`` serves stored row fields plus these computed ones:
``member_items`` (attached members, removed members excluded) and
``membership_removals`` (each recorded removal with its reason, time and any
later run holding the item). ``carried_work`` is recorded at composition
freeze; until then the read derives it live, unrecorded.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.deployment_run_carried_work_read import read_carried_work
from yoke_core.domain.deployment_run_member_presentation import (
    _member_items,
    removed_member_items,
)


LINEAGE_RUN_FIELDS = ("supersedes_run_id", "superseded_by_run_id")
COMPUTED_RUN_FIELDS = ("member_items", "membership_removals", *LINEAGE_RUN_FIELDS)


def run_lineage(run_id: str) -> dict[str, Any]:
    """Read takeover links outside the portable snapshot contract."""
    with connect() as conn:
        row = conn.execute(
            "SELECT supersedes_run_id, superseded_by_run_id "
            "FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"deployment run '{run_id}' not found")
    return {name: row[name] for name in LINEAGE_RUN_FIELDS}


def run_membership(
    run_id: str, *, visible: set[int] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Attached members without the removed ones, and every recorded removal."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, created_at, membership_removals FROM deployment_runs "
            "WHERE id=%s",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"deployment run '{run_id}' not found")
        removed = removed_member_items(
            conn, [dict(row)], visible_project_ids=visible
        ).get(run_id, [])
        excluded = {entry["id"] for entry in removed}
        members = [
            member
            for member in _member_items(
                conn, [run_id], visible_project_ids=visible
            ).get(run_id, [])
            if member["id"] not in excluded
        ]
        return {"member_items": members, "membership_removals": removed}
    finally:
        conn.close()


def live_carried_work(run_id: str) -> dict[str, Any]:
    """The recorded carried work, or the live derivation before freeze."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, status, release_lineage, bound_sources, carried_work "
            "FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"deployment run '{run_id}' not found")
        return read_carried_work(conn, dict(row))
    finally:
        conn.close()


def carried_work_for(run_id: str, stored: Mapping[str, Any]) -> dict[str, Any]:
    """Prefer the record already read; derive only when it is unrecorded."""
    recorded = parse_carried_work(stored.get("carried_work"))
    return recorded if recorded is not None else live_carried_work(run_id)


__all__ = [
    "COMPUTED_RUN_FIELDS",
    "carried_work_for",
    "live_carried_work",
    "run_membership",
]
