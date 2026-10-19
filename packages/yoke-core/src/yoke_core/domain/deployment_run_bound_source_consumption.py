"""Durable evidence that a stage already used a project's bound source."""

from __future__ import annotations
from typing import Any
from yoke_core.domain.deploy_pipeline_github_workflow_inputs import (
    workflow_dispatch_request_id,
)
from yoke_core.domain.deployment_run_bound_sources import declared_bindings
from yoke_core.domain.schema_common import _table_exists


def consumed_stage(
    conn: Any, run_id: str, project: str, stages: list, current: str
) -> str:
    """Durable stage position/dispatch evidence also protects older runs."""
    owner = conn.execute(
        "SELECT p.slug FROM deployment_runs dr JOIN projects p ON p.id=dr.project_id WHERE dr.id=%s",
        (run_id,),
    ).fetchone()[0]
    current = current.removesuffix("-failed")
    names = [str(stage.get("name") or "") for stage in stages]
    position = names.index(current) if current in names else -1
    for index, stage in enumerate(stages):
        if project not in {
            entry["project"] for entry in declared_bindings([stage]).values()
        }:
            continue
        name = str(stage["name"])
        if current == "complete" or (position >= 0 and index < position):
            return name
        # Pending provider ambiguity already consumes the source.
        if not _table_exists(conn, "github_workflow_dispatch_intents"):
            if not current:
                continue
            raise ValueError(
                f"bound_source_consumption_unverified: {run_id} has no durable dispatch store; "
                "create a new run rather than changing a potentially consumed source"
            )
        if _dispatch_recorded(conn, str(owner), run_id, name):
            return name
    return ""


def _dispatch_recorded(conn: Any, owner: str, run_id: str, stage_name: str) -> bool:
    request_id = workflow_dispatch_request_id(owner, run_id, stage_name)
    return bool(
        conn.execute(
            "SELECT 1 FROM github_workflow_dispatch_intents WHERE (request_id=%s OR LEFT(request_id,%s)=%s) AND state<>'rejected' LIMIT 1",
            (request_id, len(request_id) + 1, request_id + ":"),
        ).fetchone()
    )


def stage_dispatched(conn: Any, run_id: str, stage_name: str) -> bool:
    """Whether this run itself recorded a provider dispatch for the stage.

    A re-drive of that stage reattaches to the started workflow, so its sealed
    inputs stay authoritative however the bound branch moved since. A retry
    run copies consumption but never this run's dispatch intent.
    """
    if not _table_exists(conn, "github_workflow_dispatch_intents"):
        return False
    owner = conn.execute(
        "SELECT p.slug FROM deployment_runs dr JOIN projects p ON p.id=dr.project_id WHERE dr.id=%s",
        (run_id,),
    ).fetchone()[0]
    return _dispatch_recorded(conn, str(owner), run_id, stage_name)


def source_consumed_by(conn: Any, run_id: str, entry: dict[str, Any]) -> str:
    if (
        entry.get("consumed_by")
        or entry.get("outputs")
        or entry.get("promotion_receipts")
    ):
        return str(entry.get("consumed_by") or "release output")
    row = conn.execute(
        "SELECT df.stages,dr.current_stage FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow WHERE dr.id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    import json

    return consumed_stage(
        conn,
        run_id,
        str(entry["project"]),
        json.loads(str(row[0] or "[]")),
        str(row[1] or ""),
    )
