"""Which deployment run occupies a server, and whether another may deploy there.

A run's QA walks the build it froze. Deploying a different build to the
same server while that walk is open makes every verdict it records describe
a build nobody is serving any more. So a run *occupies* each server it
targets from the moment it starts executing until its QA settles and its
remaining stages are safe to share, or the run reaches a terminal status.
Observation-only runs can share an origin once every holder has only proven
read, QA and settlement stages left. Until its first QA stage, a run holds
its servers against deploys even if it has no members and owes no QA.

The unit is the server's origin (``scheme://host[:port]``), not the
environment record and not the project: two environment records in two
projects that name one host are one occupancy unit, with no configuration
saying so. Production origins are occupied exactly like stage ones, which
is what keeps a later release from overtaking an earlier one on the same
production server.

A run on the same flow and target that waits only on item QA does not stay in
the way of a newer candidate containing it: creating that newer run takes it
over (:mod:`yoke_core.domain.deployment_run_target_takeover`).

Frozen previews occupy their own slugs instead
(:mod:`yoke_core.domain.deploy_ephemeral_occupancy`); a run with no
persistent environment has no origin to occupy here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_policy import (
    QA_SCOPES,
    QA_STEP_RUNNER,
    STAGE_KIND_EXECUTION,
    STAGE_KIND_QA,
)
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
    return tuple(stage if isinstance(stage, Mapping) else {} for stage in stages)


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


def _is_qa_stage(stage: Mapping[str, Any]) -> bool:
    return (
        stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
    )


def _observation_only(stages: tuple[Mapping[str, Any], ...]) -> bool:
    """Allow only frozen stages whose runner is known to leave the build alone."""
    return bool(stages) and all(
        stage.get("name")
        and (
            (_is_qa_stage(stage) and str(stage.get("scope") or "") in QA_SCOPES)
            or (
                stage.get("stage_kind") == STAGE_KIND_EXECUTION
                and stage.get("step_runner") in ("warm-up", "auto")
            )
        )
        for stage in stages
    )


def _remaining_stages(target: RunTarget) -> tuple[Mapping[str, Any], ...]:
    names = [stage.get("name") for stage in target.stages]
    if not target.current_stage or names.count(target.current_stage) != 1:
        return ()
    return target.stages[names.index(target.current_stage) :]


def _open_qa_lines(
    conn: Any, target: RunTarget, *, first_wait: bool = False
) -> Optional[tuple[str, ...]]:
    """QA lines *target* still waits on; empty once every QA stage settled.

    ``None`` means the run has no QA stage, so only a terminal status
    releases it. A run whose cursor has not reached its first QA stage is
    still deploying and answers that one line. A stage that cannot be
    evaluated counts as open: an unreadable answer is not a settled one.
    """
    from yoke_core.domain.deployment_qa_stage_outstanding import (
        first_waiting_qa_stage,
        qa_stage_outstanding,
    )

    names = [str(stage.get("name") or "") for stage in target.stages]
    qa_stages = [name for name, stage in zip(names, target.stages) if _is_qa_stage(stage)]
    if not qa_stages:
        return None
    current = target.current_stage
    if current not in names or names.index(current) < names.index(qa_stages[0]):
        return (f"deploying: stage {current or 'not started'}",)
    lines: list[str] = []
    for name in qa_stages:
        read_stage = first_waiting_qa_stage if first_wait else qa_stage_outstanding
        outstanding = read_stage(
            conn,
            run_id=target.run_id,
            stage_name=name,
        )
        if outstanding is None:
            lines.append(f"stage {name}: QA state could not be read")
        else:
            lines.extend(f"stage {name}: {line}" for line in outstanding.lines)
        if first_wait and lines:
            break
    return tuple(lines)


_NO_QA_STAGE_LINE = "no QA stage: held until the run is terminal"


def open_qa_lines(
    conn: Any, run_id: str, *, first_wait: bool = False
) -> tuple[str, ...]:
    """What still holds *run_id*'s origins; empty once its QA settled."""
    target = run_target(conn, run_id)
    if target is None:
        return ()
    lines = _open_qa_lines(conn, target, first_wait=first_wait)
    return (_NO_QA_STAGE_LINE,) if lines is None else lines


def target_blockers(conn: Any, contender: RunTarget) -> list[Occupancy]:
    """Return the executing runs that prevent this contender from starting."""
    wanted = set(contender.origins)
    if not wanted:
        return []
    observing = _observation_only(contender.stages)
    p = _marker(conn)
    rows = conn.execute(
        f"{_RUN_SQL} WHERE dr.status = {p} "
        f"AND dr.superseded_by_run_id IS NULL AND dr.id <> {p} ORDER BY dr.id",
        (OCCUPYING_STATUS, contender.run_id),
    ).fetchall()
    held: list[Occupancy] = []
    for row in rows:
        target = _run_target(conn, row)
        shared = wanted.intersection(target.origins)
        if not shared:
            continue
        can_share = _observation_only(_remaining_stages(target))
        if observing and can_share:
            continue
        open_lines = _open_qa_lines(conn, target, first_wait=True)
        if open_lines == () and can_share:
            continue
        lines = open_lines
        if lines is None:
            lines = (_NO_QA_STAGE_LINE,)
        elif not lines:
            lines = ("remaining stages may change the target",)
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
        "still holds a server this run targets. Starting now could change "
        "the build that one of the runs needs to verify."
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
    return compose_refusal(
        "\n".join(lines),
        recovery="re-run this start once the holder finishes deploying and "
        "its QA settles and its remaining stages are safe to share "
        f"(`yoke deployment-runs stages {holders[0]}` shows it). A holder on "
        "this run's flow and target that now waits only on item QA is taken "
        "over during creation only when its remaining stages are QA, approval, "
        "or automatic completion, its candidate is contained, and its live "
        "driver permits takeover. Inspect those conditions before creating a "
        "replacement; recreating alone does not clear occupancy. "
        "A holder nobody will finish is released by "
        f"terminalizing it: `yoke deployment-runs terminalize {holders[0]} "
        '--disposition cancelled --reason "<why it is abandoned>"`.',
    )


def require_target_unoccupied(conn: Any, run_id: str) -> RunTarget:
    """Lock *run_id*'s origins and refuse any conflicting holder.

    Call inside the transaction that marks the run executing: the advisory
    locks are released when it commits, by which time this run's own
    executing status is what the next caller reads.
    """
    target = run_target(conn, run_id)
    if target is None:
        raise LookupError(f"deployment run {run_id} not found")
    _lock_origins(conn, target.origins)
    held = target_blockers(conn, target)
    if held:
        raise DeployTargetOccupiedError(occupied_refusal(run_id, held))
    return target


__all__ = [
    "DeployTargetOccupiedError",
    "OCCUPYING_STATUS",
    "Occupancy",
    "RunTarget",
    "occupied_refusal",
    "open_qa_lines",
    "require_target_unoccupied",
    "run_target",
    "target_blockers",
]
