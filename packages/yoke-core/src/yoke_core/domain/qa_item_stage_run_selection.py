"""Which live deployment run answers ``--item PREFIX-N --stage S``.

An item can be a member of several live runs at once: a Stage and a
Production pair, a takeover successor beside its retired source, a
supplemental proof run. The item's open requirement rows at S name the run
that owes its QA: wherever their ``deployment_run_id`` points now (a takeover
successor included), not waived, superseded, retracted or passed. A
memberless shared-plan row is the driver's, never the item form's.

With no open row yet, a run executing S qualifies when the item owes it a
case at the run's environment, read from each case's own ``target_envs``
rather than its plan's header. More than one qualifying run is refused with
every candidate named; the holder picks one with ``--deployment-run-id``. A
live run holding the rows before reaching S is named with its status and
stage, so the walker waits for its wake instead of asking for a new run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_management import QaPlanError

#: A run that has not reached a terminal status.
LIVE_STATUSES = ("created", "queued", "executing")


class QaItemStageUnavailable(QaPlanError):
    code = "qa_item_stage_unavailable"


class QaItemStageAmbiguous(QaPlanError):
    code = "qa_item_stage_ambiguous"


class QaItemRunNotMember(QaPlanError):
    code = "qa_item_run_not_member"


class QaItemRunNoRequirements(QaPlanError):
    code = "qa_item_run_no_requirements"


@dataclass(frozen=True)
class StageRun:
    """One live run and the item's open requirement ids it holds at S."""

    run_id: str
    status: str
    current_stage: str
    environment: str
    requirement_ids: tuple[int, ...] = ()

    def describe(self) -> str:
        held = (
            "requirements " + ", ".join(str(rid) for rid in self.requirement_ids)
            if self.requirement_ids
            else "no requirements yet"
        )
        return (
            f"{self.run_id} (environment {self.environment or 'unset'}, "
            f"{self.status} at stage {self.current_stage or 'none'!r}, {held})"
        )


def open_stage_holds(conn: Any, *, item_id: int, stage: str) -> list[StageRun]:
    """Live runs holding this member's open rows at *stage*, newest first."""
    from yoke_core.domain.qa_latest_execution import latest_execution_id_sql

    rows = query_rows(
        conn,
        "SELECT r.id AS run_id, r.status, COALESCE(r.current_stage,'') AS current_stage, "
        "COALESCE(e.name,'') AS environment, q.id AS requirement_id "
        "FROM qa_requirements q JOIN deployment_runs r ON r.id=q.deployment_run_id "
        "LEFT JOIN environments e ON e.id=r.target_environment_id "
        "WHERE q.deployment_member_item_id=%s AND q.deployment_stage=%s "
        "AND r.status=ANY(%s) AND r.settling_at IS NULL "
        "AND q.waived_at IS NULL AND q.superseded_at IS NULL AND q.retracted_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs x "
        f"WHERE x.id=({latest_execution_id_sql('q.id')}) AND x.verdict='pass') "
        "ORDER BY r.created_at DESC, r.id DESC, q.id",
        (int(item_id), stage, list(LIVE_STATUSES)),
    )
    held: dict[str, StageRun] = {}
    for row in rows:
        run_id = str(row["run_id"])
        found = held.get(run_id) or StageRun(
            run_id,
            str(row["status"]),
            str(row["current_stage"]),
            str(row["environment"]),
        )
        held[run_id] = StageRun(
            found.run_id,
            found.status,
            found.current_stage,
            found.environment,
            (*found.requirement_ids, int(row["requirement_id"])),
        )
    return list(held.values())


def select_stage_run(
    conn: Any,
    *,
    item_id: int,
    stage: str,
    item_ref: str,
    plan: dict[str, Any] | None = None,
    requested_run_id: str | None = None,
) -> str:
    """The run id that answers this item's QA at *stage*, or a named refusal."""
    holds = open_stage_holds(conn, item_id=item_id, stage=stage)
    if requested_run_id:
        return _validated_run(
            conn, item_id=item_id, stage=stage, item_ref=item_ref, plan=plan,
            run_id=str(requested_run_id), holds=holds,
        )
    at_stage = [hold for hold in holds if _at_stage(hold, stage)]
    if len(at_stage) == 1:
        return at_stage[0].run_id
    if at_stage:
        raise _ambiguous(item_ref, stage, at_stage)
    if holds:
        raise QaItemStageUnavailable(_pending_text(item_ref, stage, holds))
    fresh = _fresh_stage_runs(conn, item_id=item_id, stage=stage, plan=plan)
    if len(fresh) == 1:
        return fresh[0].run_id
    if fresh:
        raise _ambiguous(item_ref, stage, fresh)
    raise QaItemStageUnavailable(_new_run_text(conn, item_id, item_ref, stage))


def _at_stage(run: StageRun, stage: str) -> bool:
    return run.status == "executing" and run.current_stage == stage


def _fresh_stage_runs(
    conn: Any, *, item_id: int, stage: str, plan: dict[str, Any] | None
) -> list[StageRun]:
    """Member runs executing *stage* that could take this item's first rows.

    A run whose rows at the stage are all settled already answered; it is
    kept only when no other run is left, so a settled stage still reprints.
    """
    from yoke_core.domain.deployment_item_completion_runs import (
        completion_runs,
        uncarried_supplemental_run,
    )

    runs = [
        run
        for run in completion_runs(conn, item_id, include_qa=True)
        if run["status"] == "executing"
        and not run["settling"]
        and run["current_stage"] == stage
        and not uncarried_supplemental_run(conn, run, item_id)
    ]
    found = [
        StageRun(run["id"], "executing", stage, _run_environment(conn, run["id"]))
        for run in runs
    ]
    if len(found) > 1:
        found = [
            run for run in found if owes_case(conn, item_id, run, plan)
        ] or found
    if len(found) > 1:
        found = [
            run for run in found if not _has_stage_rows(conn, item_id, stage, run.run_id)
        ] or found
    return found


def owes_case(
    conn: Any, item_id: int, run: StageRun, plan: dict[str, Any] | None
) -> bool:
    """Whether a case of the item's plans (or *plan*) runs at this run's environment."""
    from yoke_core.domain.deployment_qa_member_plans import (
        cases_owed,
        members_plan_ids,
    )

    if plan is None:
        return bool(members_plan_ids(conn, [item_id], run.run_id).get(item_id))
    from yoke_core.domain.qa_plan_case_definition import plans_cases

    header = _environment_name(conn, plan.get("target_environment_id"))
    reaches = not header or header == run.environment
    cases = plans_cases(conn, [int(plan["id"])])[int(plan["id"])]
    return cases_owed(cases, run.environment, reaches=reaches)


def _validated_run(
    conn: Any,
    *,
    item_id: int,
    stage: str,
    item_ref: str,
    plan: dict[str, Any] | None,
    run_id: str,
    holds: list[StageRun],
) -> str:
    row = query_one(
        conn,
        "SELECT r.status, COALESCE(r.current_stage,'') AS current_stage, "
        "COALESCE(e.name,'') AS environment FROM deployment_runs r "
        "LEFT JOIN environments e ON e.id=r.target_environment_id WHERE r.id=%s",
        (run_id,),
    )
    if row is None:
        raise QaItemRunNotMember(
            f"qa_item_run_not_member: no deployment run {run_id!r} exists. "
            f"Omit --deployment-run-id to resolve {item_ref}'s run, or read its "
            f"runs with `yoke items detail get {item_ref}`."
        )
    run = StageRun(run_id, str(row["status"]), str(row["current_stage"]), str(row["environment"]))
    if any(hold.run_id == run_id for hold in holds):
        return run_id
    member = query_one(
        conn,
        "SELECT 1 AS found FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, int(item_id)),
    )
    elsewhere = "; ".join(hold.describe() for hold in holds)
    hint = f" Its open {stage!r} requirements are on {elsewhere}." if holds else ""
    if member is None:
        raise QaItemRunNotMember(
            f"qa_item_run_not_member: {item_ref} is not a member of run {run_id}."
            f"{hint} Name a run that holds {item_ref}, or omit --deployment-run-id."
        )
    if _has_stage_rows(conn, item_id, stage, run_id) or owes_case(conn, item_id, run, plan):
        return run_id
    raise QaItemRunNoRequirements(
        f"qa_item_run_no_requirements: run {run_id} holds no {stage!r} requirements "
        f"for {item_ref}, and no case of its plans targets that run's environment "
        f"{run.environment or 'unset'}.{hint} Name the run that holds them, or "
        "omit --deployment-run-id."
    )


def _has_stage_rows(conn: Any, item_id: int, stage: str, run_id: str) -> bool:
    return query_one(
        conn,
        "SELECT 1 AS found FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id=%s AND deployment_stage=%s",
        (run_id, int(item_id), stage),
    ) is not None


def _run_environment(conn: Any, run_id: str) -> str:
    row = query_one(
        conn,
        "SELECT COALESCE(e.name,'') AS name FROM deployment_runs r "
        "LEFT JOIN environments e ON e.id=r.target_environment_id WHERE r.id=%s",
        (run_id,),
    )
    return str(row["name"]) if row else ""


def _environment_name(conn: Any, environment_id: Any) -> str:
    if environment_id is None:
        return ""
    row = query_one(conn, "SELECT name FROM environments WHERE id=%s", (environment_id,))
    return str(row["name"]) if row else ""


def _ambiguous(item_ref: str, stage: str, runs: list[StageRun]) -> QaItemStageAmbiguous:
    listed = "; ".join(run.describe() for run in runs)
    return QaItemStageAmbiguous(
        f"qa_item_stage_ambiguous: {len(runs)} live runs answer {stage!r} for "
        f"{item_ref}: {listed}. Retry naming one with "
        f"`--deployment-run-id RUN` beside `--item {item_ref} --stage {stage}`."
    )


def _pending_text(item_ref: str, stage: str, holds: list[StageRun]) -> str:
    listed = "; ".join(hold.describe() for hold in holds)
    first = holds[0].run_id
    return (
        f"qa_item_stage_unavailable: {item_ref}'s {stage!r} requirements are "
        f"held by live run {listed}, which has not reached {stage!r}. Wait for "
        f"that run's {stage!r} wake, then read `yoke qa plan partitions --item {item_ref} "
        f"--stage {stage} --deployment-run-id {first}`. Do not start a new "
        "deployment: this run already enrolls the item."
    )


def _new_run_text(conn: Any, item_id: int, item_ref: str, stage: str) -> str:
    import shlex
    from uuid import uuid4

    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow

    project = query_one(
        conn,
        "SELECT p.slug FROM projects p JOIN items i ON i.project_id=p.id WHERE i.id=%s",
        (int(item_id),),
    )
    stage_flow = query_one(
        conn,
        "SELECT f.id FROM deployment_flows f "
        "JOIN environments e ON e.id=f.target_environment_id "
        "JOIN items i ON i.project_id=f.project_id "
        "WHERE i.id=%s AND e.name='stage' AND f.status='active' ORDER BY f.id",
        (int(item_id),),
    )
    flow = stage_flow["id"] if stage_flow else item_completion_flow(conn, item_id)
    command = shlex.join(
        [
            "yoke", "deployment-runs", "create",
            str(project["slug"]) if project else "PROJECT",
            flow or "FLOW", "--environment", "stage",
            "--idempotency-key", str(uuid4()),
        ]
    )
    return (
        f"qa_item_stage_unavailable: no live run holds or is executing {stage!r} "
        f"for {item_ref}. Ask steering or the release driver to start a Stage run "
        f"that enrolls this item: `{command}`. The driver must select a "
        "Stage-capable flow and confirm enrollment, then drive the run to "
        f"{stage!r} before you retry QA. This recovery does not authorize the "
        "item holder to create a run."
    )


__all__ = [
    "LIVE_STATUSES",
    "QaItemRunNoRequirements",
    "QaItemRunNotMember",
    "QaItemStageAmbiguous",
    "QaItemStageUnavailable",
    "StageRun",
    "open_stage_holds",
    "owes_case",
    "select_stage_run",
]
