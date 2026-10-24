"""Source-proven replacement has its own serving-version admission boundary."""

from pydantic import Field
from yoke_core.domain.handlers import qa_plan_writes
from yoke_contracts.api.function_call import HandlerOutcome


class PlanCasesSyncRequest(qa_plan_writes.PlanCasesReplaceRequest):
    source_revision: str = Field(
        min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$"
    )


class PlanCasesSyncResponse(qa_plan_writes.PlanCasesReplaceResponse):
    source_revision: str


def handle_plan_cases_sync(request):
    payload, error = qa_plan_writes._payload(
        request, PlanCasesSyncRequest, target_kind="global"
    )
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases
    from yoke_core.domain.qa_plan_case_currency import plan_drift_report

    try:
        with connect() as conn:
            qa_plan_writes._project_matches(
                conn, plan_id=payload.plan_id, project=payload.project
            )
            result = replace_plan_cases(
                conn,
                plan_id=payload.plan_id,
                cases=payload.cases,
                source_revision=payload.source_revision,
            )
            result.update(plan_drift_report(conn, payload.plan_id))
            result["source_revision"] = payload.source_revision
    except QaPlanError as exc:
        return qa_plan_writes._error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


def register(registry):
    registry.register(
        "qa.plan_cases.sync",
        handle_plan_cases_sync,
        PlanCasesSyncRequest,
        PlanCasesSyncResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_plan_source_sync",
        target_kinds=["global"],
        minimum_serving_version="next-release",
        side_effects=["qa_plan_cases_replace"],
        guardrails=["project_scope_required", "snapshot_preserved"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
