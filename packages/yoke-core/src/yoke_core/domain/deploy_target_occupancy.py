"""Which deployment run occupies a server, and whether another may deploy there.

A run's QA walks the build it froze. Deploying a different build to the
same server while that walk is open makes every verdict it records describe
a build nobody is serving any more. So a run *occupies* each server it
targets from the moment it starts executing until its QA stages settle or
the run reaches a terminal status, and a second run that would deploy to an
occupied server refuses before it changes anything.

The unit is the server's origin (``scheme://host[:port]``), not the
environment record and not the project: two environment records in two
projects that name one host are one occupancy unit, with no configuration
saying so. Production origins are occupied exactly like stage ones, which
is what keeps a later release from overtaking an earlier one on the same
production server.

Frozen previews occupy their own slugs instead
(:mod:`yoke_core.domain.deploy_ephemeral_occupancy`); a run with no
persistent environment has no origin to occupy here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.deployment_target_identity_config import (
    environment_urls,
    qa_target_environment_names,
)
from yoke_core.domain.served_revision_probe import origin_of

#: The run statuses that may hold an origin. A created run has not deployed
#: anything yet; a terminal run has released whatever it held.
OCCUPYING_STATUS = "executing"


class DeployTargetOccupiedError(ValueError):
    """Raised when a run would deploy to an origin another run occupies."""


@dataclass(frozen=True)
class RunTarget:
    """One run's deploy footprint: its project, stages, and origins."""

    run_id: str
    project_id: int
    current_stage: str
    stages: tuple[Mapping[str, Any], ...]
    origins: tuple[str, ...]


@dataclass(frozen=True)
class Occupancy:
    """A run holding *origin*, and the QA lines it is still waiting on."""

    origin: str
    run_id: str
    project_id: int
    current_stage: str
    open_requirements: tuple[str, ...]


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _stages(raw: Any) -> tuple[Mapping[str, Any], ...]:
    try:
        stages = json.loads(str(raw or "[]")) if not isinstance(raw, list) else raw
    except (TypeError, ValueError):
        return ()
    if not isinstance(stages, list):
        return ()
    return tuple(stage for stage in stages if isinstance(stage, Mapping))


_RUN_SQL = """SELECT dr.id, dr.project_id, dr.current_stage, df.stages,
                     e.name AS target_environment
                FROM deployment_runs dr
                JOIN deployment_flows df ON df.id = dr.flow
           LEFT JOIN environments e ON e.id = dr.target_environment_id"""


def _run_target(conn: Any, row: Any) -> RunTarget:
    project_id = int(_value(row, "project_id", 1))
    stages = _stages(_value(row, "stages", 3))
    names = qa_target_environment_names(list(stages))
    target_environment = str(_value(row, "target_environment", 4) or "")
    if target_environment:
        names.append(target_environment)
    urls = environment_urls(conn, project_id, names)
    origins = sorted({origin_of(url) for url in urls.values() if url})
    return RunTarget(
        run_id=str(_value(row, "id", 0)),
        project_id=project_id,
        current_stage=str(_value(row, "current_stage", 2) or ""),
        stages=stages,
        origins=tuple(origins),
    )


def run_target(conn: Any, run_id: str) -> Optional[RunTarget]:
    """The origins *run_id* deploys to, or ``None`` for an unknown run."""
    row = conn.execute(
        f"{_RUN_SQL} WHERE dr.id = {_marker(conn)}", (run_id,)
    ).fetchone()
    return _run_target(conn, row) if row is not None else None


def _open_qa_lines(conn: Any, target: RunTarget) -> Optional[tuple[str, ...]]:
    """QA lines *target* still waits on; empty once every QA stage settled.

    ``None`` means the run has no QA stage, so only a terminal status
    releases it. A stage that cannot be evaluated counts as open: an
    unreadable answer is not a settled one.
    """
    from yoke_core.domain.deployment_qa_stage_outstanding import (
        qa_stage_outstanding,
    )

    qa_stages = [
        str(stage.get("name") or "")
        for stage in target.stages
        if stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
    ]
    if not qa_stages:
        return None
    lines: list[str] = []
    for name in qa_stages:
        outstanding = qa_stage_outstanding(conn, run_id=target.run_id, stage_name=name)
        if outstanding is None:
            lines.append(f"stage {name}: QA state could not be read")
            continue
        lines.extend(f"stage {name}: {line}" for line in outstanding.lines)
    return tuple(lines)


def occupancies(
    conn: Any, origins: Iterable[str], *, excluding_run: str = ""
) -> list[Occupancy]:
    """Every executing run that still occupies one of *origins*."""
    wanted = set(origins)
    if not wanted:
        return []
    p = _marker(conn)
    rows = conn.execute(
        f"{_RUN_SQL} WHERE dr.status = {p} AND dr.id <> {p} ORDER BY dr.id",
        (OCCUPYING_STATUS, excluding_run),
    ).fetchall()
    held: list[Occupancy] = []
    for row in rows:
        target = _run_target(conn, row)
        shared = wanted.intersection(target.origins)
        if not shared:
            continue
        open_lines = _open_qa_lines(conn, target)
        if open_lines == ():
            continue
        lines = open_lines or ("no QA stage: held until the run is terminal",)
        held.extend(
            Occupancy(
                origin=origin,
                run_id=target.run_id,
                project_id=target.project_id,
                current_stage=target.current_stage,
                open_requirements=lines,
            )
            for origin in sorted(shared)
        )
    return held


def _lock_origins(conn: Any, origins: Iterable[str]) -> None:
    """Serialize every start on these origins until this transaction ends.

    Sorted so two runs sharing several origins take them in one order and
    cannot deadlock against each other.
    """
    if not db_backend.connection_is_postgres(conn):
        return
    for origin in sorted(set(origins)):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"deploy_target:{origin}",),
        )


def occupied_refusal(run_id: str, held: list[Occupancy]) -> str:
    """The refusal naming each holder, its open QA, and the recovery."""
    lines = [
        f"deployment run {run_id} refused: target_occupied. Another run is "
        "still being verified on a server this run would deploy to, and "
        "deploying now would replace the build its QA is walking."
    ]
    for occupancy in held:
        lines.append(
            f"- {occupancy.origin} is held by run {occupancy.run_id} "
            f"(project {occupancy.project_id}, stage "
            f"{occupancy.current_stage or 'not started'}); open:"
        )
        lines.extend(f"    {line}" for line in occupancy.open_requirements[:10])
        if len(occupancy.open_requirements) > 10:
            lines.append(f"    … {len(occupancy.open_requirements) - 10} more")
    holders = sorted({occupancy.run_id for occupancy in held})
    lines.append(
        "Recovery: re-run this start once the holder's QA settles "
        f"(`yoke deployment-runs stages {holders[0]}` shows it). A holder "
        "nobody will finish is released by terminalizing it: "
        f"`yoke deployment-runs terminalize {holders[0]} --disposition "
        'cancelled --reason "<why it is abandoned>"`.'
    )
    return "\n".join(lines)


def require_target_unoccupied(conn: Any, run_id: str) -> RunTarget:
    """Lock *run_id*'s origins and refuse if another run still holds one.

    Call inside the transaction that marks the run executing: the advisory
    locks are released when it commits, by which time this run's own
    executing status is what the next caller reads.
    """
    target = run_target(conn, run_id)
    if target is None:
        raise LookupError(f"deployment run {run_id} not found")
    _lock_origins(conn, target.origins)
    held = occupancies(conn, target.origins, excluding_run=run_id)
    if held:
        raise DeployTargetOccupiedError(occupied_refusal(run_id, held))
    return target


__all__ = [
    "DeployTargetOccupiedError",
    "OCCUPYING_STATUS",
    "Occupancy",
    "RunTarget",
    "occupancies",
    "occupied_refusal",
    "require_target_unoccupied",
    "run_target",
]
