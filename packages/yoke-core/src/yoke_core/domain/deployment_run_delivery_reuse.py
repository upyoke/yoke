"""Reuse a delivery the target already serves instead of dispatching it again.

A run whose bound workflow stage would ship exactly what its target already
serves gains nothing from dispatching: the same commits rebuild, the tenant
copy repeats and a new pin may land, all to reach a later stage. The proof
that a target serves a pair of commits is the newest succeeded run on it: an
environment of this run's name, for this run's project or any project the
stage binds, in any flow. Its promotion receipt for every bound project must
name this run's ``release_lineage`` as ``product_sha`` and this run's bound
commit as ``platform_sha``. One workflow ships every project, so the reuse is
all-or-nothing; a newer deploy of either project, or an earlier run that
never produced a promotion receipt, simply dispatches.

A reuse copies the matched receipts into this run's bound entries, seals them
consumed by the stage, and records ``delivery_reuse[stage]`` naming the run
whose delivery stands in, all in one write. A repeated call answers from
that record, so a driver whose answer was lost cannot reuse twice.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    declared_bindings,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_project_sources import (
    invalidate_run_source_facts,
)
from yoke_core.domain.deployment_runs_lock import bounded_run_write, lock_run
from yoke_core.domain.hosted_promotion_receipt import (
    PROMOTION_RECEIPTS_KEY,
    project_promotion_receipts,
)
from yoke_core.domain.json_helper import dumps_compact, loads_text

DELIVERY_REUSE_FUNCTION_ID = "deployment_runs.execution.delivery_reuse"
DELIVERY_REUSE_KEY = "delivery_reuse"


def _decline(reason: str) -> dict[str, str]:
    return {"reused_run_id": "", "reason": reason}


def _newest_delivery(
    conn: Any, run_id: str, environment: str, project_ids: list[int]
) -> tuple[str, dict[str, Any]] | None:
    marks = ",".join(["%s"] * len(project_ids))
    row = conn.execute(
        f"SELECT dr.id,COALESCE(dr.{BOUND_SOURCES_FIELD},'') FROM deployment_runs dr "
        "JOIN environments e ON e.id=dr.target_environment_id "
        f"WHERE dr.status='succeeded' AND dr.id<>%s AND e.name=%s "
        f"AND dr.project_id IN ({marks}) "
        "ORDER BY dr.completed_at DESC NULLS LAST,dr.created_at DESC,dr.id DESC "
        "LIMIT 1",
        (run_id, environment, *project_ids),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), parse_bound_sources(row[1])


def _mismatch(
    receipts: list[dict[str, Any]],
    *,
    project: str,
    lineage: str,
    bound_sha: str,
    environment: str,
) -> str:
    if not receipts:
        return f"it recorded no promotion receipt for {project}"
    payload = receipts[-1].get("payload") or {}
    for key, expected in (
        ("target_environment", environment),
        ("product_sha", lineage),
        ("platform_sha", bound_sha),
    ):
        if payload.get(key) != expected:
            return (
                f"its {project} promotion receipt names {key} "
                f"{payload.get(key)!r}, not this run's {expected!r}"
            )
    return ""


def reuse_delivery(conn: Any, run_id: str, stage_name: str) -> dict[str, str]:
    """Reuse the target's served delivery for ``stage_name`` when it matches.

    Returns ``reused_run_id`` naming the run whose delivery stands in, or an
    empty id with the ``reason`` the stage must dispatch. The caller commits.
    """
    with bounded_run_write(conn, run_id):
        if lock_run(conn, run_id) is None:
            raise LookupError(f"deployment run {run_id!r} not found")
        row = conn.execute(
            f"SELECT dr.project_id,COALESCE(dr.release_lineage,''),"
            f"COALESCE(dr.{BOUND_SOURCES_FIELD},''),dr.status,df.stages,"
            "COALESCE(e.name,'') FROM deployment_runs dr "
            "JOIN deployment_flows df ON df.id=dr.flow "
            "LEFT JOIN environments e ON e.id=dr.target_environment_id "
            "WHERE dr.id=%s",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"deployment run {run_id!r} not found")
        own_project_id, lineage, stored, status, stages_text, environment = row
        if status != "executing":
            raise ValueError(
                f"delivery_reuse_run_not_executing: {run_id} is {status}; "
                f"re-drive it with `yoke watch deploy -- {run_id}`"
            )
        sources = parse_bound_sources(stored)
        recorded = (sources.get(DELIVERY_REUSE_KEY) or {}).get(stage_name)
        if recorded:
            return {"reused_run_id": str(recorded["run_id"]), "reason": ""}
        stages = loads_text(str(stages_text or "[]"))
        stage = next((s for s in stages if s.get("name") == stage_name), None)
        if stage is None:
            raise ValueError(
                f"delivery_reuse_stage_unknown: {run_id} has no stage {stage_name!r}"
            )
        needed = {b["project"] for b in declared_bindings([stage]).values()}
        if not needed:
            return _decline("the stage binds no project a promotion receipt proves")
        if not environment:
            return _decline("the run names no target environment")
        updated = deepcopy(sources)
        entries = [e for e in updated["projects"] if e.get("project") in needed]
        if {e["project"] for e in entries} != needed:
            return _decline("the run records no bound commit for every project")
        if any(e.get("consumed_by") for e in entries):
            return _decline("this run already consumed the bound source")
        project_ids = sorted({int(own_project_id), *(int(e["project_id"]) for e in entries)})
        newest = _newest_delivery(conn, run_id, environment, project_ids)
        if newest is None:
            return _decline(f"no succeeded run has delivered to {environment}")
        prior_run_id, prior_sources = newest
        receipts = {}
        for entry in entries:
            found = project_promotion_receipts(prior_sources, int(entry["project_id"]))
            mismatch = _mismatch(
                found,
                project=entry["project"],
                lineage=lineage,
                bound_sha=str(entry.get("commit_sha") or ""),
                environment=environment,
            )
            if mismatch:
                return _decline(
                    f"the newest {environment} delivery {prior_run_id} differs: {mismatch}"
                )
            receipts[entry["project"]] = found[-1]
        stamp = format_instant(utc_now())
        for entry in entries:
            entry["consumed_by"] = stage_name
            entry["consumed_at"] = stamp
            entry[PROMOTION_RECEIPTS_KEY] = [receipts[entry["project"]]]
        updated.setdefault(DELIVERY_REUSE_KEY, {})[stage_name] = {
            "run_id": prior_run_id,
            "recorded_at": stamp,
        }
        conn.execute(
            f"UPDATE deployment_runs SET {BOUND_SOURCES_FIELD}=%s WHERE id=%s",
            (dumps_compact(updated), run_id),
        )
        invalidate_run_source_facts(conn, run_id)
    return {"reused_run_id": prior_run_id, "reason": ""}


__all__ = [
    "DELIVERY_REUSE_FUNCTION_ID",
    "DELIVERY_REUSE_KEY",
    "reuse_delivery",
]
