"""Continue a mission walk whose execution was settled while it was parked.

A walker told to hold parks, and a parked walker stops heartbeating. When
that silence outlives the session -- a sleep, a reload, an end -- the stale
sweep settles the execution and terminal settlement stamps its captures with
an error verdict. The walk itself is not lost: the Test Machine still holds
the partial state the walk built. What is lost is the way back in, because a
fresh execution re-runs the case's host baseline and wipes exactly that
state.

A continuation is the way back in. It is an ordinary new execution over the
same roster, recording its own runs, with one difference carried on the row
itself: ``continues_execution_id`` names the settled execution it resumes,
and no case in a continuation reaches a host baseline. The prior execution
stays as history with the reason it ended; the continuation's own run becomes
the requirement's latest, which is what supersedes the swept error verdict on
every projection that reads the latest run.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.qa_plan_execution_lifecycle import (
    STALE_PLAN_EXECUTION_REASON,
)
from yoke_core.domain.qa_plan_execution_schema import (
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    marker,
    select_plan_execution,
)

CONTINUATION_FLAG = "--continue-mission"


def skips_host_baseline(execution: Mapping[str, Any]) -> bool:
    """True when this execution inherits a host it must not reset."""
    return bool(execution.get("continues_execution_id"))


def contract_baselines(
    execution: Mapping[str, Any],
    case: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return the host baselines this case's issued contract may reach.

    A continuation reaches none: it exists because the host still holds the
    state a settled walk built, and running the case's baseline would destroy
    exactly that. The suppression is read from the execution row rather than
    from the roster, so the immutable case snapshot still matches its live
    requirement when the protocol re-checks it.
    """
    if skips_host_baseline(execution):
        return ()
    baseline = str(case.get("host_baseline") or "")
    return (baseline,) if baseline else ()


def _mission_ordinals(execution: Mapping[str, Any]) -> list[int]:
    return [
        index
        for index, case in enumerate(execution.get("roster") or [])
        if case.get("runner_id") == "agent_mission"
    ]


def _baseline_resetting_case(execution: Mapping[str, Any]) -> dict[str, Any] | None:
    for case in execution.get("roster") or []:
        if case.get("runner_id") == "host_control" and case.get("host_baseline"):
            return dict(case)
    return None


def latest_plan_execution(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the most recent execution recorded for one QA subject."""
    placeholder = marker(conn)
    if (item_id is None) == (deployment_run_id is None):
        raise QaPlanExecutionStateError(
            "exactly one QA plan execution subject is required"
        )
    if item_id is not None:
        where = f"item_id={placeholder} AND transition_id={placeholder}"
        params: tuple[Any, ...] = (int(item_id), str(transition_id))
    else:
        where = f"deployment_run_id={placeholder}"
        params = (str(deployment_run_id),)
    row = conn.execute(
        f"SELECT id FROM qa_plan_executions WHERE {where} "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    if row is None:
        return None
    execution_id = row["id"] if hasattr(row, "keys") else row[0]
    return select_plan_execution(conn, str(execution_id), lock=False)


def require_continuable_execution(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
) -> dict[str, Any]:
    """Return the settled mission execution a continuation may resume.

    Every refusal names the condition that failed and the command that does
    apply, because the caller reaching here is a walker that has already been
    refused once by the mission it is trying to get back into.
    """
    prior = latest_plan_execution(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
    )
    if prior is None:
        raise QaPlanExecutionStateError(
            f"{CONTINUATION_FLAG} found no prior QA plan execution for this "
            "subject; run the plan without it to start one"
        )
    state = str(prior["state"])
    reason = str(prior.get("release_reason") or "")
    if state not in TERMINAL_PLAN_EXECUTION_STATES:
        raise QaPlanExecutionStateError(
            f"QA plan execution {prior['id']} is still {state!r}; "
            f"drop {CONTINUATION_FLAG} to resume the live execution"
        )
    if reason != STALE_PLAN_EXECUTION_REASON:
        raise QaPlanExecutionStateError(
            f"QA plan execution {prior['id']} ended as {state!r} because "
            f"{reason!r}, not because the stale sweep settled a parked walk; "
            f"only a swept execution may be continued, so drop "
            f"{CONTINUATION_FLAG} and run the plan fresh"
        )
    if not _mission_ordinals(prior):
        raise QaPlanExecutionStateError(
            f"QA plan execution {prior['id']} ran no agent-mission case; a "
            "continuation exists to re-enter a mission on the host it left "
            f"behind, so drop {CONTINUATION_FLAG} and run the plan fresh"
        )
    resetting = _baseline_resetting_case(prior)
    if resetting is not None:
        raise QaPlanExecutionStateError(
            "QA plan execution "
            f"{prior['id']} also runs host-control requirement "
            f"{resetting['requirement_id']} against host baseline "
            f"{resetting['host_baseline']!r}, which would reset the very host "
            "state a continuation inherits; drop "
            f"{CONTINUATION_FLAG} and run the plan fresh"
        )
    return prior


def resolve_continuation_source(
    conn: Any,
    *,
    live_execution_id: str | None,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
) -> str:
    """Return the settled execution id a requested continuation resumes."""
    try:
        if live_execution_id is not None:
            raise QaPlanExecutionStateError(
                f"QA plan execution {live_execution_id} is still live for this "
                f"subject; drop {CONTINUATION_FLAG} to resume it"
            )
        prior = require_continuable_execution(
            conn,
            item_id=item_id,
            transition_id=transition_id,
            deployment_run_id=deployment_run_id,
        )
    except QaPlanExecutionStateError:
        conn.rollback()
        raise
    return str(prior["id"])


def continuation_recipe(conn: Any, execution: Mapping[str, Any]) -> str:
    """Render the exact command that continues *execution*'s walk."""
    if execution.get("item_id") is not None:
        from yoke_core.domain.project_identity import render_item_ref

        public_ref = render_item_ref(conn, int(execution["item_id"]))
        subject = (
            f"--item {public_ref} "
            f"--transition {str(execution.get('transition_id') or '')}"
        )
    else:
        subject = (
            f"--deployment-run-id {str(execution.get('deployment_run_id') or '')} "
            f"--plan {_plan_slug(conn, execution)} "
            f"--project {_project_slug(execution)}"
        )
    return f"yoke qa plan run {subject} {CONTINUATION_FLAG}"


def mission_access_refusal(conn: Any, execution: Mapping[str, Any]) -> str:
    """Say why a mission is unreachable, and name the way back in.

    A walker that parked on instruction meets this refusal on its first
    command after resuming, and a bare state mismatch dead-ends it. When the
    stale sweep is what settled the execution, the refusal carries the exact
    continuation command instead.
    """
    state = str(execution["state"])
    base = (
        "mission access requires awaiting_agent_review; execution "
        f"{execution['id']} is {state!r}"
    )
    settled_by_sweep = (
        state in TERMINAL_PLAN_EXECUTION_STATES
        and str(execution.get("release_reason") or "") == STALE_PLAN_EXECUTION_REASON
    )
    if not settled_by_sweep:
        return base
    return (
        f"{base} because the stale sweep settled it. The Test Machine still "
        "holds this walk's state; continue it, keeping that state and "
        "skipping the host baseline, with: "
        f"{continuation_recipe(conn, execution)}"
    )


def _plan_slug(conn: Any, execution: Mapping[str, Any]) -> str:
    roster = execution.get("roster") or []
    plan_ids = [case.get("plan_id") for case in roster if case.get("plan_id")]
    if not plan_ids:
        return "<plan-slug>"
    row = conn.execute(
        f"SELECT slug FROM qa_plans WHERE id={marker(conn)}",
        (int(plan_ids[0]),),
    ).fetchone()
    if row is None:
        return "<plan-slug>"
    return str(row["slug"] if hasattr(row, "keys") else row[0])


def _project_slug(execution: Mapping[str, Any]) -> str:
    for case in execution.get("roster") or []:
        if case.get("project"):
            return str(case["project"])
    return "<project-slug>"


__all__ = [
    "CONTINUATION_FLAG",
    "contract_baselines",
    "continuation_recipe",
    "latest_plan_execution",
    "mission_access_refusal",
    "require_continuable_execution",
    "resolve_continuation_source",
    "skips_host_baseline",
]
