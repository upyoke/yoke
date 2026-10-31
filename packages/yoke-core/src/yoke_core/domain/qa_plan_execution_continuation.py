"""Continue stale-settled mission walks without resetting their preserved host.

The prior execution stays as history; continuation runs supersede its verdict.
"""

from __future__ import annotations

from yoke_contracts.qa_case_starting_state import needs_test_machine

from typing import Any, Mapping

from yoke_core.domain.qa_plan_execution_abort_reason import (
    CASE_EXECUTION_ERROR_REASON,
    PRE_HOST_ERROR_REASON,
    REASON_DETAIL_SEPARATOR,
    abort_reason_code,
    error_abort_reason,
)
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
    STANDALONE_HISTORY_ORDER_SQL,
)

CONTINUATION_FLAG = "--continue-mission"


def skips_host_baseline(execution: Mapping[str, Any]) -> bool:
    """True when this execution inherits a host it must not reset."""
    return bool(execution.get("continues_execution_id"))


def contract_baselines(
    execution: Mapping[str, Any],
    case: Mapping[str, Any],
) -> tuple[str, ...]:
    from yoke_contracts.qa_case_starting_state import reset_baselines

    return tuple(reset_baselines(case, continues=skips_host_baseline(execution)))


def continuation_abort_reason(
    execution: Mapping[str, Any], error: BaseException
) -> str:
    """Return a durable reason that preserves proven pre-host retries.

    The reason carries what failed as well as which class of failure it was.
    Without the diagnosis, an execution's release evidence names only that
    "a case execution or recording error" happened, and the one reader who
    has to repair it -- the person the refusal sends to inspect that
    evidence -- has nothing to inspect.
    """
    if not getattr(error, "host_contact_possible", True):
        code = PRE_HOST_ERROR_REASON
    else:
        code = CASE_EXECUTION_ERROR_REASON
    return error_abort_reason(code, error)


def _failed_before_host(conn: Any, execution: Mapping[str, Any]) -> bool:
    """Recognize explicit failures and the original zero-result row shape."""
    if not execution.get("continues_execution_id"):
        return False
    reason = abort_reason_code(execution.get("release_reason"))
    if reason == PRE_HOST_ERROR_REASON:
        return True
    if reason != CASE_EXECUTION_ERROR_REASON or int(execution["cursor_ordinal"]):
        return False
    row = conn.execute(
        f"SELECT 1 FROM qa_plan_execution_results WHERE execution_id={marker(conn)} "
        "LIMIT 1",
        (str(execution["id"]),),
    ).fetchone()
    return row is None


def _mission_ordinals(execution: Mapping[str, Any]) -> list[int]:
    return [
        index
        for index, case in enumerate(execution.get("roster") or [])
        if case.get("runner_id") == "agent_mission" and needs_test_machine(case)
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
    standalone_plan_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Return a QA subject's latest execution; a stage-wide one per session."""
    placeholder = marker(conn)
    if standalone_plan_id is not None:
        row = conn.execute(
            f"SELECT id FROM qa_plan_executions WHERE standalone_plan_id={placeholder} "
            f"ORDER BY {STANDALONE_HISTORY_ORDER_SQL} LIMIT 1",
            (standalone_plan_id,),
        ).fetchone()
        return select_plan_execution(conn, str(row[0]), lock=False) if row else None
    if (item_id is None) == (deployment_run_id is None):
        raise QaPlanExecutionStateError(
            "exactly one QA plan execution subject is required"
        )
    if item_id is not None:
        where = f"item_id={placeholder} AND transition_id={placeholder}"
        params: tuple[Any, ...] = (int(item_id), str(transition_id))
    else:
        where = (
            f"deployment_run_id={placeholder} "
            f"AND COALESCE(deployment_stage,'')={placeholder} "
            f"AND COALESCE(deployment_member_item_id,0)={placeholder}"
        )
        params = (
            str(deployment_run_id),
            deployment_stage or "",
            deployment_member_item_id or 0,
        )
        if deployment_stage and deployment_member_item_id is None:
            where += f" AND session_id={placeholder}"
            params += (str(session_id or ""),)
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
    standalone_plan_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    session_id: str | None = None,
    expected_execution_id: str | None = None,
) -> dict[str, Any]:
    """Return the settled mission execution a continuation may resume.

    Every refusal names the condition that failed and the command that does
    apply, because the caller reaching here is a walker that has already been
    refused once by the mission it is trying to get back into.
    """
    prior = latest_plan_execution(
        conn,
        standalone_plan_id=standalone_plan_id,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
        session_id=session_id,
    )
    if prior is None:
        raise QaPlanExecutionStateError(
            f"{CONTINUATION_FLAG} found no prior QA plan execution for this "
            "subject; run the plan without it to start one"
        )
    if _failed_before_host(conn, prior):
        prior = select_plan_execution(
            conn, str(prior["continues_execution_id"]), lock=False
        )
    if expected_execution_id is not None and str(prior["id"]) != expected_execution_id:
        raise QaPlanExecutionStateError(
            "qa_continuation_source_changed: the latest eligible walk differs from "
            "the requested execution; inspect its history before continuing"
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
            "continuation is unsafe without a settled source. Preserve the "
            "Test Machine state, inspect this execution's release evidence, "
            f"and repair that evidence before retrying {CONTINUATION_FLAG}"
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
    deployment_stage: str | None = None,
    deployment_member_item_id: int | None = None,
    session_id: str | None = None,
    expected_execution_id: str | None = None,
) -> str:
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
            deployment_stage=deployment_stage,
            deployment_member_item_id=deployment_member_item_id,
            session_id=session_id,
            expected_execution_id=expected_execution_id,
        )
    except QaPlanExecutionStateError:
        conn.rollback()
        raise
    return str(prior["id"])


def continuation_recipe(conn: Any, execution: Mapping[str, Any]) -> str:
    """Render the exact command that continues *execution*'s walk."""
    return (
        f"yoke qa plan run --resume-execution-id {execution['id']} {CONTINUATION_FLAG}"
    )


def mission_access_refusal(conn: Any, execution: Mapping[str, Any]) -> str:
    """Say why a mission is unreachable, and name the way back in.

    A walker that parked on instruction meets this refusal on its first
    command after resuming, and a bare state mismatch dead-ends it. When the
    stale sweep is what settled the execution, the refusal carries the exact
    continuation command instead.
    """
    state = str(execution["state"])
    base = f"mission access requires walking; execution {execution['id']} is {state!r}"
    if state not in TERMINAL_PLAN_EXECUTION_STATES:
        return base
    if str(execution.get("release_reason") or "") != STALE_PLAN_EXECUTION_REASON:
        from yoke_core.domain.qa_plan_execution_abort_state import (
            SERVER_FIXTURE_CLEANUP,
        )

        return (
            f"{base}, so no walker can reach it. Walk nothing more and run no "
            f"host command. {SERVER_FIXTURE_CLEANUP} Then return this refusal "
            "with what is still present: the main owner judges the missions "
            "recorded before the stop from their evidence, through the "
            "dispatch that `yoke qa plan review-begin` prints with this walk's "
            f"subject flag and --execution-id {execution['id']}"
        )
    return (
        f"{base} because the stale sweep settled it. The Test Machine still "
        "holds this walk's state; continue it, keeping that state and "
        "skipping the host baseline, with: "
        f"{continuation_recipe(conn, execution)}"
    )


__all__ = [
    "CASE_EXECUTION_ERROR_REASON",
    "REASON_DETAIL_SEPARATOR",
    "abort_reason_code",
    "CONTINUATION_FLAG",
    "PRE_HOST_ERROR_REASON",
    "contract_baselines",
    "continuation_abort_reason",
    "continuation_recipe",
    "latest_plan_execution",
    "mission_access_refusal",
    "require_continuable_execution",
    "resolve_continuation_source",
    "skips_host_baseline",
]
