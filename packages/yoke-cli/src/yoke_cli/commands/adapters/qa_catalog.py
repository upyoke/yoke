from __future__ import annotations

import argparse
import json
from typing import Any, Callable, List

from yoke_cli.commands._helpers import (
    detail_of,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.qa_execution_subjects import (
    qa_artifact_read,
    qa_plan_materialize_for_item,
    qa_plan_rematerialize,
)
from yoke_cli.commands.adapters.qa_catalog_parser import (
    build_item_plan_attach_parser,
    build_parser,
    configure_activity_list,
    configure_method_get,
    configure_method_register,
    configure_plan_create,
    configure_plan_get,
)
from yoke_cli.commands.adapters.qa_catalog_usage import (
    PLAN_CASES_SYNC_USAGE,
    USAGE_BY_FUNCTION_ID,
)
from yoke_cli.commands.adapters.qa_plan_listing import qa_plan_list
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.adapters.qa_plan_source_input import (
    case_payload as _case_payload,
    configure_case_replace as _configure_case_replace,
)


def _global(
    args: List[str],
    *,
    prog: str,
    usage: str,
    function_id: str,
    configure: Callable[[argparse.ArgumentParser], None] | None = None,
    payload: Callable[[argparse.Namespace], dict[str, Any]],
    project_required: bool = True,
) -> int:
    parser = build_parser(prog, usage, project_required=project_required)
    if configure is not None:
        configure(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        built_payload = payload(parsed)
    except (OSError, ValueError) as exc:
        return usage_error(str(exc))
    if function_id == "qa.plan_cases.replace" and "source_revision" in built_payload:
        return usage_error(
            "qa_plan_source_sync_required: replace accepts manual case arrays; use yoke qa plan-cases sync for source exports"
        )
    if function_id == "qa.plan_cases.sync" and "source_revision" not in built_payload:
        return usage_error(
            "qa_plan_source_revision_required: pass the exporter's document or add --source-revision "
            "FULL_SHA; author manual case arrays with yoke qa plan-cases replace"
        )
    if parsed.project:
        built_payload = {"project": parsed.project, **built_payload}
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=built_payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def qa_method_list(args: List[str]) -> int:
    return _global(
        args,
        prog="yoke qa method list",
        usage="yoke qa method list [--project P] [--full] [--session-id S] [--json]",
        function_id="qa.method.list",
        payload=lambda _args: {},
        project_required=False,
    )


def qa_method_get(args: List[str]) -> int:
    return _global(
        args,
        prog="yoke qa method get",
        usage=(
            "yoke qa method get METHOD [--project P] [--full] "
            "[--session-id S] [--json]"
        ),
        function_id="qa.method.get",
        configure=configure_method_get,
        payload=lambda parsed: {"method_id": parsed.method_id},
        project_required=False,
    )


def qa_method_register(args: List[str]) -> int:
    usage = (
        "yoke qa project-method register --project P --slug SLUG --name NAME "
        "--description TEXT --runner worktree_run|browser_substrate "
        "--verdict-path automatic|agent --verdict-contract TEXT "
        "--evidence-contract TEXT [--concurrency-mode parallel|serial] "
        "[--required-capability KIND ...] "
        "[--success-policy-params JSON] [--session-id S] [--json]"
    )

    def payload(parsed: argparse.Namespace) -> dict[str, Any]:
        policy = json.loads(parsed.success_policy_params)
        if not isinstance(policy, dict):
            raise ValueError("success policy params must be a JSON object")
        return {
            "slug": parsed.slug,
            "name": parsed.name,
            "description": parsed.description,
            "runner_id": parsed.runner,
            "verdict_path": parsed.verdict_path,
            "verdict_contract": parsed.verdict_contract,
            "evidence_contract": parsed.evidence_contract,
            "required_capability_kinds": parsed.required_capability_kinds,
            "concurrency_mode": parsed.concurrency_mode,
            "success_policy_params": policy,
        }

    return _global(
        args,
        prog="yoke qa project-method register",
        usage=usage,
        function_id="qa.project_method.register",
        configure=configure_method_register,
        payload=payload,
    )


def qa_plan_get(args: List[str]) -> int:
    usage = USAGE_BY_FUNCTION_ID["qa.plan.get"]

    def payload(parsed: argparse.Namespace) -> dict[str, Any]:
        if (parsed.plan is None) == (parsed.plan_id is None):
            raise ValueError(
                "provide exactly one plan id or slug, positionally or with --plan-id"
            )
        detail = detail_of(parsed)
        plan = parsed.plan if parsed.plan is not None else parsed.plan_id
        result: dict[str, Any] = {
            "plan_id": int(plan) if plan.isdecimal() else plan,
            "detail": detail,
        }
        if parsed.deployment_run_id:
            result["deployment_run_id"] = parsed.deployment_run_id
        return result

    return _global(
        args,
        prog="yoke qa plan get",
        usage=usage,
        function_id="qa.plan.get",
        configure=configure_plan_get,
        payload=payload,
    )


def qa_activity_list(args: List[str]) -> int:
    usage = USAGE_BY_FUNCTION_ID["qa.activity.list"]

    def payload(parsed: argparse.Namespace) -> dict[str, Any]:
        result: dict[str, Any] = {"limit": parsed.limit}
        if parsed.deployment_run_id:
            result["deployment_run_id"] = parsed.deployment_run_id
        if parsed.item:
            result["public_refs"] = list(parsed.item)
        return result

    return _global(
        args,
        prog="yoke qa activity list",
        usage=usage,
        function_id="qa.activity.list",
        configure=configure_activity_list,
        payload=payload,
    )


def qa_plan_create(args: List[str]) -> int:
    usage = (
        "yoke qa plan create SLUG --project P "
        "--environment SITE/NAME|ENV_ID "
        "[--name NAME] [--description TEXT] [--session-id S] [--json]"
    )
    return _global(
        args,
        prog="yoke qa plan create",
        usage=usage,
        function_id="qa.plan.create",
        configure=configure_plan_create,
        payload=lambda parsed: {
            "slug": parsed.slug,
            "name": parsed.name,
            "description": parsed.description,
            "target_environment": parsed.environment,
        },
    )


def qa_plan_cases_replace(args: List[str]) -> int:
    usage = (
        "yoke qa plan-cases replace --project P --plan-id N "
        "(--cases-file PATH | --stdin) [--source-revision FULL_SHA] "
        "[--session-id S] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        _configure_case_replace(
            parser,
            source_revision_help=(
                "Refused here: cases exported from source go through "
                "yoke qa plan-cases sync."
            ),
        )

    return _global(
        args,
        prog="yoke qa plan-cases replace",
        usage=usage,
        function_id="qa.plan_cases.replace",
        configure=configure,
        payload=_case_payload,
    )


def qa_plan_cases_sync(args: List[str]) -> int:
    return _global(
        args,
        prog="yoke qa plan-cases sync",
        usage=PLAN_CASES_SYNC_USAGE,
        function_id="qa.plan_cases.sync",
        configure=_configure_case_replace,
        payload=_case_payload,
    )


def qa_plan_item_attach(args: List[str]) -> int:
    usage = (
        "yoke qa item-plan attach --item PREFIX-N --project P --plan-id N "
        "--transition T [--qa-phase PHASE] [--acknowledge-unreachable-target] "
        "[--session-id S] [--json]"
    )
    parser = build_item_plan_attach_parser(usage)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.item_plan.attach",
        target=item_target("item", parsed.item, parsed.project),
        payload={
            "project": parsed.project,
            "plan_id": parsed.plan_id,
            "transition_id": parsed.transition,
            "qa_phase": parsed.qa_phase,
            "acknowledge_unreachable_target": parsed.acknowledge_unreachable_target,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "qa_activity_list",
    "qa_artifact_read",
    "qa_method_get",
    "qa_method_list",
    "qa_method_register",
    "qa_plan_cases_replace",
    "qa_plan_cases_sync",
    "qa_plan_create",
    "qa_plan_get",
    "qa_plan_item_attach",
    "qa_plan_list",
    "qa_plan_materialize_for_item",
    "qa_plan_rematerialize",
]
