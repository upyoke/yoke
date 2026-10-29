"""Registered materialization handler for item and deployment-run QA plans."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class MaterializeRequest(BaseModel):
    transition_id: Optional[str] = Field(default=None, min_length=1)
    plan: Optional[str] = Field(default=None, min_length=1)
    project: Optional[str] = Field(default=None, min_length=1)
    deployment_stage: Optional[str] = Field(default=None, min_length=1)
    deployment_member: Optional[str] = Field(default=None, min_length=1)
    replacements: list["ReplacementDeclaration"] = Field(default_factory=list)


class ReplacementDeclaration(BaseModel):
    case_key: str | None = Field(default=None, min_length=1)
    requirement_id: int = Field(..., gt=0)


MaterializeRequest.model_rebuild()


class RematerializeRequest(BaseModel):
    # An item subject names its transition; a deployment subject names the
    # pinned stage, and its member when the stage is item-scoped.
    transition_id: str | None = None
    deployment_stage: str | None = None
    deployment_member: str | None = None
    plan: str | None = None


def _subject_unavailable(exc: BaseException) -> HandlerOutcome:
    return _error(
        getattr(exc, "code", "qa_subject_unavailable"),
        "deployment QA subject is unavailable: "
        f"{exc}; use the active run stage and an attached member, then retry",
        "$.target",
    )


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_materialize(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = MaterializeRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_attachments import (
        materialize_for_deployment_run,
        materialize_for_item,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.qa_requirement_replacement import (
        QaReplacementError,
        declare_replacements,
    )

    try:
        with connect() as conn:
            from yoke_core.domain.qa_item_deployment_request import (
                resolve_item_deployment_request,
            )

            try:
                request = resolve_item_deployment_request(conn, request)
            except QaPlanError:
                raise
            except (LookupError, ValueError) as exc:
                return _subject_unavailable(exc)
            payload = MaterializeRequest.model_validate(request.payload)
            from yoke_core.domain.qa_requirement_correction_selection import (
                resolve_correction_selection,
            )

            replacements, replacement_scopes = resolve_correction_selection(
                conn, [entry.model_dump() for entry in payload.replacements]
            )
            if request.target.kind == "item":
                item_id = request.target.item_id
                if item_id is None:
                    return _error(
                        "target_invalid",
                        "public_ref (PREFIX-N) is required",
                        "$.target",
                    )
                if payload.transition_id is None:
                    return _error(
                        "payload_invalid",
                        "item materialization requires transition_id",
                        "$.payload.transition_id",
                    )
                if payload.plan is not None:
                    return _error(
                        "payload_invalid",
                        "item materialization uses attached plans, not plan",
                        "$.payload.plan",
                    )
                result = materialize_for_item(
                    conn,
                    item_id=int(item_id),
                    transition_id=payload.transition_id,
                    commit=not payload.replacements,
                    replacement_scopes=replacement_scopes,
                )
            elif request.target.kind == "deployment_run":
                run_id = request.target.deployment_run_id
                if not run_id:
                    return _error(
                        "target_invalid",
                        "deployment run id is required",
                        "$.target",
                    )
                if payload.plan is None and payload.deployment_stage is None:
                    return _error(
                        "payload_invalid",
                        "deployment-run materialization requires plan",
                        "$.payload.plan",
                    )
                if payload.transition_id is not None:
                    return _error(
                        "payload_invalid",
                        "deployment-run materialization has no workflow transition",
                        "$.payload.transition_id",
                    )
                if payload.deployment_stage is not None:
                    from yoke_core.domain.deployment_qa_stage_materialization import (
                        materialize_deployment_qa_stage,
                    )
                    from yoke_core.domain.item_ref_resolution import (
                        resolve_item_ref_or_none,
                    )

                    member_id = (
                        resolve_item_ref_or_none(conn, payload.deployment_member)
                        if payload.deployment_member is not None
                        else None
                    )
                    if payload.deployment_member is not None and member_id is None:
                        return _error(
                            "payload_invalid",
                            f"deployment member {payload.deployment_member!r} not found",
                            "$.payload.deployment_member",
                        )
                    try:
                        result = materialize_deployment_qa_stage(
                            conn,
                            deployment_run_id=str(run_id),
                            deployment_stage=payload.deployment_stage,
                            deployment_member_item_id=member_id,
                            agent_plan=payload.plan,
                            replacement_keys={
                                entry["case_key"] for entry in replacements
                            },
                            replaced_requirement_ids=frozenset(
                                entry.requirement_id for entry in payload.replacements
                            ),
                            commit=not payload.replacements,
                            replacement_scopes=replacement_scopes,
                        )
                    except QaPlanError:
                        raise
                    except (LookupError, ValueError) as exc:
                        return _subject_unavailable(exc)
                else:
                    result = materialize_for_deployment_run(
                        conn,
                        deployment_run_id=str(run_id),
                        plan=payload.plan,
                        project=payload.project,
                    )
            else:
                return _error(
                    "target_invalid",
                    "qa.plan.materialize requires an item or deployment run",
                    "$.target.kind",
                )
            if payload.replacements:
                result["replacements"] = declare_replacements(
                    conn,
                    replacements,
                    materialized_requirement_ids=[
                        *result.get("created_requirement_ids", []),
                        *result.get("existing_requirement_ids", []),
                    ],
                )
                conn.commit()
                if payload.deployment_stage is not None:
                    from yoke_core.domain.deployment_qa_correction_notice import (
                        notify_correction,
                    )

                    try:
                        result["correction_notice"] = notify_correction(
                            conn, result=result, replacements=result["replacements"]
                        )
                    except Exception as exc:  # declaration already committed
                        conn.rollback()
                        result["correction_notice"] = {
                            "delivery": "failed",
                            "recovery": f"Correction is durable but holder wake failed: {exc}. "
                            f"Run the corrected case for {run_id} stage "
                            f"{payload.deployment_stage} with --test-machine TEST_MACHINE from the failed "
                            "attempt's QA run evidence, and inspect the run.",
                        }
            elif (
                payload.deployment_stage is not None
                and result.get("existing_requirement_ids")
                and not result.get("created_requirement_ids")
            ):
                from yoke_core.domain.deployment_qa_failure_handoff import (
                    retry_command_for_stage,
                )

                recipe = retry_command_for_stage(
                    conn,
                    run_id=str(run_id),
                    stage=str(payload.deployment_stage),
                    member_ref=payload.deployment_member,
                    member_id=result.get("deployment_member_item_id"),
                    project=payload.project,
                )
                result["retry"] = (
                    "These cases already exist, so nothing was created. A failed "
                    "case is retried on its same requirement against the deployed "
                    f"release: {recipe}"
                )
    except QaPlanError as exc:
        return _error(getattr(exc, "code", "incompatible"), str(exc), "$.payload")
    except QaReplacementError as exc:
        return _error("replacement_refused", str(exc), "$.payload.replacements")
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


def handle_rematerialize(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = RematerializeRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item
    from yoke_core.domain.qa_plan_rematerialize_deployment import (
        rematerialize_for_deployment_stage,
    )

    if request.target.kind == "item" and request.target.item_id is not None:
        if payload.plan is not None and not payload.deployment_stage:
            return _error(
                "item_plan_filter_unsupported",
                "Item refresh uses attached plans. Remove plan and retry with the item transition.",
                "$.payload.plan",
            )
        if not (payload.transition_id or payload.deployment_stage):
            return _error(
                "payload_invalid",
                "qa.plan.rematerialize on an item requires transition_id",
                "$.payload.transition_id",
            )
    elif (
        request.target.kind == "deployment_run"
        and request.target.deployment_run_id is not None
    ):
        if not payload.deployment_stage:
            return _error(
                "payload_invalid",
                "qa.plan.rematerialize on a deployment run requires deployment_stage",
                "$.payload.deployment_stage",
            )
    else:
        return _error(
            "target_invalid",
            "qa.plan.rematerialize requires an item or deployment run target",
            "$.target",
        )

    try:
        with connect() as conn:
            from yoke_core.domain.qa_item_deployment_request import (
                resolve_item_deployment_request,
            )

            request = resolve_item_deployment_request(conn, request)
            payload = RematerializeRequest.model_validate(request.payload)
            if request.target.kind == "item":
                result = rematerialize_for_item(
                    conn,
                    item_id=int(request.target.item_id),
                    transition_id=str(payload.transition_id),
                )
            else:
                from yoke_core.domain.item_ref_resolution import (
                    resolve_item_ref_or_none,
                )

                member_id = (
                    resolve_item_ref_or_none(conn, payload.deployment_member)
                    if payload.deployment_member is not None
                    else None
                )
                if payload.deployment_member is not None and member_id is None:
                    return _error(
                        "not_found",
                        f"deployment member {payload.deployment_member!r} not found",
                        "$.payload.deployment_member",
                    )
                result = rematerialize_for_deployment_stage(
                    conn,
                    deployment_run_id=str(request.target.deployment_run_id),
                    deployment_stage=str(payload.deployment_stage),
                    deployment_member_item_id=member_id,
                    plan=payload.plan,
                )
    except QaPlanError as exc:
        return _error(getattr(exc, "code", "incompatible"), str(exc), "$.payload")
    except (ValueError, LookupError) as exc:
        return _error(
            "qa_refresh_subject_unavailable",
            f"QA refresh could not resolve its subject: {exc}. "
            "Inspect the item attachments or run membership with "
            "`yoke items detail get ITEM` or `yoke deployment-runs get RUN-ID`, "
            "correct the selected subject, then retry rematerialization.",
            "$.target",
        )
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


__all__ = [
    "MaterializeRequest",
    "ReplacementDeclaration",
    "RematerializeRequest",
    "handle_materialize",
    "handle_rematerialize",
]
