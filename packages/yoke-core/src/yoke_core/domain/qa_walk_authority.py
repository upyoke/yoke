"""Authorize exactly the partition assigned to a claimless walk session."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    marker,
    select_plan_execution,
)
from yoke_core.domain.qa_plan_partition_chains import partition_key
from yoke_core.domain.qa_plan_partition_custody import PartitionScope, live_partition_executions
from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit

_WALK_KEY = re.compile(r"qa-walk:([^:]+):([^:]+):([0-9a-f]{64}):([1-9][0-9]*)")
_WALK_PREFIXES = (
    "qa.plan_execution.", "qa.plan_review.", "test_machine.plan_case.", "test_machine.mission.",
)
_WALK_FUNCTIONS = frozenset({
    "qa.case_execution.begin", "qa.plan.materialize", "qa.artifact.add", "qa.artifact.presign",
})
_ARTIFACT_FUNCTIONS = {"qa.artifact.add", "qa.artifact.presign"}


class WalkAuthorityError(QaPlanExecutionStateError):
    code = "qa_walk_authority_refused"


class WalkDelegationLapsed(WalkAuthorityError):
    code = "qa_walk_delegation_lapsed"


@dataclass(frozen=True)
class WalkLaunch:
    requester: str
    leg: str
    partition: str


def walk_launch(conn, *, item_id: int, session_id: str) -> WalkLaunch | None:
    """Resolve authority only from an attested registration on a claimless launch."""
    if not session_id:
        return None
    p = marker(conn)
    rows = query_rows(
        conn,
        "SELECT requester_session_id,idempotency_key FROM session_launches "
        f"WHERE registered_session_id={p} AND item_id IS NULL "
        f"AND project_id=(SELECT project_id FROM items WHERE id={p}) "
        "AND idempotency_key LIKE 'qa-walk:%%'",
        (session_id, item_id),
    )
    if not rows:
        return None
    ref = render_item_ref(conn, item_id)
    matches = []
    for row in rows:
        parsed = _WALK_KEY.fullmatch(str(row["idempotency_key"] or ""))
        if parsed and parsed[1] == ref and row["requester_session_id"]:
            matches.append(WalkLaunch(str(row["requester_session_id"]), parsed[2], parsed[3]))
    return matches[0] if len(matches) == 1 else None


def require_walk_claim(conn, *, item_id: int, launch: WalkLaunch, lock: bool = False) -> dict:
    """Bind the launch grant to the delegating session's current item claim."""
    return _require_requester_claim(conn, item_id=item_id, requester=launch.requester, lock=lock)


def _require_requester_claim(conn, *, item_id: int, requester: str, lock: bool) -> dict:
    claim = get_claim_for_work_unit(conn, item_id=str(item_id))
    if claim and str(claim["session_id"]) == requester:
        if not lock:
            return claim
        p = marker(conn)
        if query_one(
            conn,
            f"SELECT id FROM work_claims WHERE id={p} AND session_id={p} "
            "AND released_at IS NULL FOR SHARE",
            (claim["id"], requester),
        ):
            return claim
    raise WalkDelegationLapsed(
        "qa_walk_delegation_lapsed: the requester no longer holds the item's work claim. "
        "Abort your own execution, report the lapse to the item holder, and end the walk."
    )


def require_walk_partition(launch: WalkLaunch, *, leg: str | None, key: str | None) -> None:
    if leg != launch.leg or key != launch.partition:
        raise WalkAuthorityError(
            "qa_walk_authority_refused: this launch delegates one item part. "
            "Run the transition or stage and partition named in the launch."
        )


def admitted_walk(execution: dict) -> bool:
    return bool(execution["roster"] and execution["roster"][0].get("delegated_walk"))


def require_admitted_walk_claim(conn, execution: dict, *, item_id: int, lock=False) -> dict:
    """Keep the original requester's claim live without re-admitting the cursor."""
    requester = execution["roster"][0]["delegated_walk"]
    if requester is True:
        # An already-admitted roster can predate the stored requester. Its
        # registration resolves the requester, never the current partition.
        launch = walk_launch(conn, item_id=item_id, session_id=execution["session_id"])
        requester = launch.requester if launch else None
    if not isinstance(requester, str) or not requester:
        raise WalkAuthorityError(
            "qa_walk_authority_refused: the execution's delegating session could not be "
            "resolved. Ask the item holder to inspect the execution and its assignment."
        )
    return _require_requester_claim(conn, item_id=item_id, requester=requester, lock=lock)


def _execution_matches(execution: dict, *, item_id: int, launch: WalkLaunch) -> bool:
    return bool(
        (execution.get("item_id") or execution.get("deployment_member_item_id")) == item_id
        and (execution.get("transition_id") or execution.get("deployment_stage")) == launch.leg
        and execution["roster"]
        and partition_key(execution["roster"]) == launch.partition
    )


def _artifact_execution_id(conn, *, run_id, requirement_id) -> str | None:
    if type(run_id) is not int or requirement_id is None:
        return None
    p = marker(conn)
    row = query_one(
        conn,
        f"SELECT raw_result FROM qa_runs WHERE id={p} AND qa_requirement_id={p}",
        (run_id, requirement_id),
    )
    if row and row["raw_result"]:
        try:
            evidence = json.loads(row["raw_result"])
        except (TypeError, ValueError):
            return None
        if isinstance(evidence, dict):
            execution_id = evidence.get("plan_execution_id") or evidence.get("execution_id")
            if isinstance(execution_id, str):
                return execution_id
    return None


def _case_execution(conn, requirement_id, *, item_id, session_id):
    p = marker(conn)
    row = query_one(
        conn,
        "SELECT item_id,workflow_transition_id,deployment_run_id,deployment_stage,"
        f"deployment_member_item_id FROM qa_requirements WHERE id={p}",
        (requirement_id,),
    )
    if row is None or (row["item_id"] or row["deployment_member_item_id"]) != item_id:
        return None
    scope = PartitionScope(
        row["item_id"], row["workflow_transition_id"], row["deployment_run_id"],
        row["deployment_stage"], row["deployment_member_item_id"],
    )
    return next(
        (
            execution for execution in live_partition_executions(conn, scope)
            if execution["session_id"] == session_id and any(
                case["requirement_id"] == requirement_id for case in execution["roster"]
            )
        ),
        None,
    )


def delegated_walk_grants(conn, request, *, item_id: int) -> bool:
    """Resolve each allowed leg to the immutable cursor or the launch selector."""
    function = request.function
    payload = request.payload or {}
    session_id = request.actor.session_id
    requirement = request.target.qa_requirement_id
    execution = None
    if function == "qa.plan_execution.abort":
        execution = select_plan_execution(conn, str(payload.get("execution_id") or ""), lock=False)
        if execution["session_id"] == session_id:
            return True

    if function == "qa.plan_execution.adopt":
        return bool(delegating_adoption_claim(
            conn, item_id=item_id, session_id=session_id,
            execution=select_plan_execution(conn, str(payload.get("execution_id") or ""), lock=False),
        ))
    if function == "qa.plan_execution.reconcile" or not (
        function.startswith(_WALK_PREFIXES) or function in _WALK_FUNCTIONS
    ):
        return False
    if function in {"qa.plan_execution.begin", "qa.plan.materialize"}:
        launch = walk_launch(conn, item_id=item_id, session_id=session_id)
        if launch is None:
            return False
        leg = payload.get("transition_id") or payload.get("deployment_stage")
        if function == "qa.plan_execution.begin":
            require_walk_partition(launch, leg=leg, key=payload.get("partition"))
        elif payload.get("replacements") or leg != launch.leg:
            return False
        require_walk_claim(conn, item_id=item_id, launch=launch)
    else:
        if function == "qa.case_execution.begin":
            execution = _case_execution(conn, requirement, item_id=item_id, session_id=session_id)
        elif execution is None:
            execution_id = (
                _artifact_execution_id(conn, run_id=payload.get("run_id"), requirement_id=requirement)
                if function in _ARTIFACT_FUNCTIONS else payload.get("execution_id")
            )
            if not execution_id:
                return False
            execution = select_plan_execution(conn, str(execution_id), lock=False)
        if (
            execution is None or execution["session_id"] != session_id
            or (execution.get("item_id") or execution.get("deployment_member_item_id")) != item_id
            or not admitted_walk(execution)
            or (requirement is not None and all(
                case["requirement_id"] != requirement for case in execution["roster"]
            ))
        ):
            return False
        require_admitted_walk_claim(conn, execution, item_id=item_id)
    return True


def delegating_adoption_claim(conn, *, item_id: int, session_id: str, execution: dict):
    """Only a replacement for the same delegated walk may adopt its cursor."""
    if str(execution["session_id"]) == session_id:
        return None
    launch = walk_launch(conn, item_id=item_id, session_id=session_id)
    prior = walk_launch(conn, item_id=item_id, session_id=str(execution["session_id"]))
    if launch is None or prior != launch or not _execution_matches(
        execution, item_id=item_id, launch=launch
    ):
        return None
    return require_walk_claim(conn, item_id=item_id, launch=launch)


def qa_walk_or_start_bound_verdict(request, *, item_id: int):
    """Return None when neither a start-bound claim nor a walk grants authority."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_start_bound_authority import payload_grants_authority

    if payload_grants_authority(
        request.payload, session_id=request.actor.session_id, item_id=item_id,
    ):
        return True, None, None
    if not (
        request.function.startswith(_WALK_PREFIXES) or request.function in _WALK_FUNCTIONS
    ):
        return None
    try:
        with connect() as conn:
            if delegated_walk_grants(conn, request, item_id=item_id):
                return True, None, None
    except WalkAuthorityError as exc:
        return False, exc.code, str(exc)
    except QaPlanExecutionStateError as exc:
        return False, "qa_execution_subject_invalid", str(exc)
    return None
