"""Walk-end disposal of the Yoke projects an exploratory mission created.

``yoke qa mission walk-end`` uninstalls every project its Test Machine
registers, then calls ``test_machine.mission.dispose_projects`` with that
host evidence before it restores the host or releases a cleanup lease. Only
the execution's own session may call it, and only while the execution is
live. The handler adds the projects earlier walk-ends on the run reported,
records an intent receipt naming every candidate before it changes
anything, disposes of each project the execution created (see
:mod:`qa_fixture_project_disposal`), then records the per-project
dispositions. Both receipts are ``fixture_project_disposal`` artifacts on
the mission's run. It runs on a normal walk-end and on an aborted walk's
cleanup walk-end alike."""

from __future__ import annotations

import base64
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)

FUNCTION_ID = "test_machine.mission.dispose_projects"


class MissionProjectDisposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    requirement_id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    host_projects: list[dict[str, Any]] = Field(default_factory=list)


class MissionProjectDisposalResponse(BaseModel):
    execution_id: str
    run_id: int
    projects: list[dict[str, Any]]
    unsettled: list[dict[str, Any]]
    left_for_administrator: list[dict[str, Any]]


def _authorized_execution(conn: Any, request: FunctionCallRequest, parsed) -> dict:
    from yoke_core.domain.agent_mission_cleanup import _mission
    from yoke_core.domain.handlers.machine_qa_plan_case_request import (
        target_plan_subject,
    )
    from yoke_core.domain.qa_plan_execution_authority import (
        require_plan_execution_subject,
    )
    from yoke_core.domain.qa_plan_execution_store import (
        lock_plan_execution,
        same_owner,
    )

    target = target_plan_subject(request, FUNCTION_ID)
    if isinstance(target, HandlerOutcome):
        raise ValueError(target.error.message if target.error else "invalid target")
    execution = lock_plan_execution(conn, parsed.execution_id)
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request

    request = resolve_execution_request(conn, request, execution)
    item_id, deployment_run_id = request.target.item_id, request.target.deployment_run_id
    from yoke_core.domain.qa_plan_execution_schema import (
        TERMINAL_PLAN_EXECUTION_STATES,
    )

    if execution["state"] in TERMINAL_PLAN_EXECUTION_STATES:
        raise ValueError(
            "mission_project_disposal_execution_ended: execution "
            f"{execution['id']} is {execution['state']}, so it disposes of "
            "nothing; dispose of a leftover project with yoke items cancel "
            "and yoke projects retire"
        )
    if request.target.kind == "global":
        from yoke_core.domain.qa_standalone_execution import require_standalone_project

        require_standalone_project(conn, execution, str(request.target.project_id))
    require_plan_execution_subject(
        execution, item_id=item_id, deployment_run_id=deployment_run_id
    )
    if not same_owner(
        execution, actor_id=request.actor.actor_id, session_id=request.actor.session_id
    ):
        raise ValueError(
            "mission_project_disposal_owner_required: only the execution's "
            f"original session {execution['session_id']} may dispose of its "
            "fixture projects; ask that session to rerun walk-end"
        )
    _, _, run_id = _mission(conn, execution, parsed.requirement_id)
    if parsed.run_id != run_id:
        raise ValueError(
            f"mission_project_disposal_run_mismatch: rerun walk-end with --run-id {run_id}"
        )
    conn.commit()
    return execution


def _receipted_project_ids(conn: Any, run_id: int) -> set[int]:
    """Projects earlier walk-ends on this run reported, once the host is reset."""
    from yoke_core.domain.db_helpers import query_rows
    from yoke_core.domain.qa_fixture_project_disposal import FIXTURE_PROJECT_DISPOSAL
    from yoke_core.domain.qa_plan_execution_store import marker

    p = marker(conn)
    rows = query_rows(
        conn,
        f"SELECT metadata FROM qa_artifacts WHERE qa_run_id={p} AND artifact_type={p}",
        (run_id, FIXTURE_PROJECT_DISPOSAL),
    )
    return {
        int(project_id)
        for row in rows
        for project_id in json.loads(row["metadata"] or "{}").get("project_ids", [])
    }


def _record_receipt(
    request: FunctionCallRequest, parsed, receipt: dict, project_ids: list[int]
) -> None:
    from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
    from yoke_core.domain.qa_fixture_project_disposal import FIXTURE_PROJECT_DISPOSAL

    outcome = handle_qa_artifact_add(
        request.model_copy(
            update={
                "function": "qa.artifact.add",
                "target": TargetRef(
                    kind="qa_requirement", qa_requirement_id=parsed.requirement_id
                ),
                "payload": {
                    "run_id": parsed.run_id,
                    "artifact_type": FIXTURE_PROJECT_DISPOSAL,
                    "filename": "fixture-project-disposal.json",
                    "content_type": "application/json",
                    "metadata": json.dumps({"project_ids": project_ids}),
                    "content_base64": base64.b64encode(
                        json.dumps(receipt, sort_keys=True, default=str).encode()
                    ).decode(),
                },
            }
        )
    )
    if not outcome.primary_success:
        error = outcome.error
        raise ValueError(
            "mission_project_disposal_unrecorded: "
            f"{error.code + ': ' + error.message if error else 'no artifact'}; "
            "rerun walk-end once the run accepts artifacts"
        )


def handle_mission_project_disposal(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.machine_qa import _failure
    from yoke_core.domain.handlers.machine_qa_plan_case_request import (
        parse_plan_case_request,
    )
    from yoke_core.domain.machine_qa_submission_artifacts import (
        ensure_secret_free_result,
    )
    from yoke_core.domain.qa_fixture_project_disposal import (
        dispose_projects,
        left_for_administrator,
        unsettled,
    )

    parsed = parse_plan_case_request(MissionProjectDisposalRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = connect()
    try:
        ensure_secret_free_result(parsed.host_projects)
        execution = _authorized_execution(conn, request, parsed)
        candidates = sorted(
            {int(entry["project_id"]) for entry in parsed.host_projects}
            | _receipted_project_ids(conn, parsed.run_id)
        )
        # The intent receipt lands before any change, so a rerun after the
        # host's restore still reaches every candidate.
        intent = {"phase": "intent", "host_projects": parsed.host_projects}
        _record_receipt(request, parsed, intent, candidates)
        projects = dispose_projects(
            conn,
            execution,
            candidates,
            actor_id=int(request.actor.actor_id),
            session_id=str(request.actor.session_id or ""),
        )
        _record_receipt(
            request,
            parsed,
            {**intent, "phase": "result", "projects": projects},
            candidates,
        )
    except (KeyError, LookupError, ValueError) as exc:
        conn.rollback()
        return _failure(
            "mission_project_disposal_failed",
            f"{exc}; rerun walk-end after resolving the named blocker",
        )
    finally:
        conn.close()
    response = MissionProjectDisposalResponse(
        execution_id=str(execution["id"]),
        run_id=parsed.run_id,
        projects=projects,
        unsettled=unsettled(projects),
        left_for_administrator=left_for_administrator(projects),
    )
    return HandlerOutcome(primary_success=True, result_payload=response.model_dump())


def request_project_disposal(
    *,
    target: TargetRef,
    actor: ActorContext,
    execution_id: str,
    requirement_id: int,
    run_id: int,
    host_projects: list[dict[str, Any]],
) -> tuple[list[str], list[str], bool]:
    """Ask the control plane to dispose of the walk's projects.

    Returns the named failures a rerun can settle, notices that never block
    walk-end, and whether the control plane recorded a receipt; without one,
    the caller must not restore the host.
    """
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id=FUNCTION_ID,
        target=target,
        actor=actor,
        payload={
            "execution_id": execution_id,
            "requirement_id": requirement_id,
            "run_id": run_id,
            "host_projects": host_projects,
        },
    )
    if not response.success:
        error = response.error
        return (
            [
                "fixture_project_disposal_failed: "
                + (f"{error.code}: {error.message}" if error else "no disposal receipt")
                + "; rerun this walk-end"
            ],
            [],
            False,
        )
    failures = [
        f"fixture_project_uninstall_failed: {entry['checkout']} "
        f"({entry['reason']}) on the Test Machine. Read the "
        "fixture_project_disposal artifact on the run for the step output, "
        "then rerun this walk-end"
        for entry in host_projects
        if not entry.get("uninstalled")
    ]
    for entry in (response.result or {}).get("unsettled", []):
        failures.append(
            f"fixture_project_not_disposed: project {entry['slug'] or entry['project_id']} "
            f"is {entry['disposition']}"
            + (f" ({entry['error']})" if entry.get("error") else "")
            + "".join(
                f"; {failure['item']} not cancelled: {failure['error']}"
                for failure in entry.get("item_failures", [])
            )
            + ". Resolve the named blocker, then rerun this walk-end"
        )
    notices = [
        f"fixture_project_left_for_administrator: project {entry['slug']} was "
        "created during this walk but you do not administer it; an "
        f"administrator runs yoke projects retire --project {entry['slug']} "
        "--reason 'QA fixture project'"
        for entry in (response.result or {}).get("left_for_administrator", [])
    ]
    return failures, notices, True


def register(registry: Any) -> None:
    registry.register(
        FUNCTION_ID,
        handle_mission_project_disposal,
        MissionProjectDisposalRequest,
        MissionProjectDisposalResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "global"],
        minimum_serving_version="next-release",
        side_effects=[
            "cancel_item",
            "project_retirement_write",
            "coordination_claim_release",
            "qa_artifacts_insert",
        ],
        emitted_event_names=["ProjectRetirementChanged", "YokeFunctionCalled"],
        guardrails=["qa_subject_authority", "actor_session_bound"],
        adapter_status="internal",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
    )


__all__ = [
    "FUNCTION_ID",
    "handle_mission_project_disposal",
    "register",
    "request_project_disposal",
]
