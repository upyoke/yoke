"""Computed membership and live carried work for one deployment-run read.

``deployment_runs.get`` serves stored row fields plus these computed ones:
``member_items`` (attached members, removed members excluded) and
``membership_removals`` (each recorded removal with its reason, time and any
later run holding the item). ``carried_work`` is recorded at composition
freeze; until then the read derives it live, unrecorded.
"""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_carried_work_read import read_carried_work
from yoke_core.domain.deployment_run_member_presentation import (
    _member_items,
    removed_member_items,
)


COMPUTED_RUN_FIELDS = ("member_items", "membership_removals")
LIVE_RUN_FIELDS = ("carried_work",)


def computed_run_fields(run_id: str, names: Iterable[str]) -> dict[str, Any]:
    """Answer each requested computed or live field for an existing run."""
    wanted = set(names)
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, status, release_lineage, bound_sources, carried_work, "
            "created_at, membership_removals FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"deployment run '{run_id}' not found")
        run = dict(row)
        values: dict[str, Any] = {}
        if wanted & set(COMPUTED_RUN_FIELDS):
            removed = removed_member_items(conn, [run]).get(run_id, [])
            excluded = {entry["id"] for entry in removed}
            values["member_items"] = [
                member
                for member in _member_items(conn, [run_id]).get(run_id, [])
                if member["id"] not in excluded
            ]
            values["membership_removals"] = removed
        if "carried_work" in wanted:
            values["carried_work"] = read_carried_work(conn, run)
        return {name: values[name] for name in wanted if name in values}
    finally:
        conn.close()


__all__ = ["COMPUTED_RUN_FIELDS", "LIVE_RUN_FIELDS", "computed_run_fields"]
