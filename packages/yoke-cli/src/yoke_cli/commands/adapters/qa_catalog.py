"""Flag adapters for the project QA method and plan catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
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
from yoke_cli.commands.adapters.qa_catalog_usage import USAGE_BY_FUNCTION_ID
from yoke_contracts.api.function_call import TargetRef


def _parser(prog: str, usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _global(
    args: List[str],
    *,
    prog: str,
    usage: str,
    function_id: str,
    configure: Callable[[argparse.ArgumentParser], None] | None = None,
    payload: Callable[[argparse.Namespace], dict[str, Any]],
) -> int:
    parser = _parser(prog, usage)
    if configure is not None:
        configure(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        built_payload = payload(parsed)
    except (OSError, ValueError) as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, **built_payload},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def qa_method_list(args: List[str]) -> int:
    usage = "yoke qa method list --project P [--json]"
    return _global(
        args,
        prog="yoke qa method list",
        usage=usage,
        function_id="qa.method.list",
        payload=lambda _args: {},
    )


def qa_method_get(args: List[str]) -> int:
    usage = "yoke qa method get METHOD --project P [--json]"
    return _global(
        args,
        prog="yoke qa method get",
        usage=usage,
        function_id="qa.method.get",
        configure=lambda parser: parser.add_argument("method_id"),
        payload=lambda parsed: {"method_id": parsed.method_id},
    )


def _configure_method_register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument(
        "--runner",
        required=True,
        choices=(
            "worktree_run",
            "browser_substrate",
        ),
    )
    parser.add_argument(
        "--verdict-path",
        required=True,
        choices=("automatic", "agent"),
    )
    parser.add_argument("--verdict-contract", required=True)
    parser.add_argument("--evidence-contract", required=True)
    parser.add_argument(
        "--required-capability",
        dest="required_capability_kinds",
        action="append",
    )
    parser.add_argument(
        "--concurrency-mode",
        choices=("parallel", "serial"),
        default="parallel",
    )
    parser.add_argument("--success-policy-params", default="{}")


def qa_method_register(args: List[str]) -> int:
    usage = (
        "yoke qa project-method register --project P --slug SLUG --name NAME "
        "--description TEXT --runner worktree_run|browser_substrate "
        "--verdict-path automatic|agent --verdict-contract TEXT "
        "--evidence-contract TEXT [--concurrency-mode parallel|serial] "
        "[--required-capability KIND ...] "
        "[--success-policy-params JSON] [--json]"
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
        configure=_configure_method_register,
        payload=payload,
    )


def qa_plan_list(args: List[str]) -> int:
    usage = "yoke qa plan list --project P [--json]"
    return _global(
        args,
        prog="yoke qa plan list",
        usage=usage,
        function_id="qa.plan.list",
        payload=lambda _args: {},
    )


def qa_plan_get(args: List[str]) -> int:
    usage = "yoke qa plan get PLAN_ID --project P [--deployment-run-id RUN] [--json]"

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("plan_id", type=int)
        parser.add_argument("--deployment-run-id")

    def payload(parsed: argparse.Namespace) -> dict[str, Any]:
        result: dict[str, Any] = {"plan_id": parsed.plan_id}
        if parsed.deployment_run_id:
            result["deployment_run_id"] = parsed.deployment_run_id
        return result

    return _global(
        args,
        prog="yoke qa plan get",
        usage=usage,
        function_id="qa.plan.get",
        configure=configure,
        payload=payload,
    )


def qa_activity_list(args: List[str]) -> int:
    usage = (
        "yoke qa activity list --project P "
        "[--deployment-run-id RUN] [--limit N] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--deployment-run-id")
        parser.add_argument("--limit", type=int, default=100)

    def payload(parsed: argparse.Namespace) -> dict[str, Any]:
        result: dict[str, Any] = {"limit": parsed.limit}
        if parsed.deployment_run_id:
            result["deployment_run_id"] = parsed.deployment_run_id
        return result

    return _global(
        args,
        prog="yoke qa activity list",
        usage=usage,
        function_id="qa.activity.list",
        configure=configure,
        payload=payload,
    )


def _configure_plan_create(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--name")
    parser.add_argument("--description", default="")
    parser.add_argument("--environment", required=True)


def qa_plan_create(args: List[str]) -> int:
    usage = (
        "yoke qa plan create SLUG --project P "
        "--environment ENV [--name NAME] [--description TEXT] [--json]"
    )
    return _global(
        args,
        prog="yoke qa plan create",
        usage=usage,
        function_id="qa.plan.create",
        configure=_configure_plan_create,
        payload=lambda parsed: {
            "slug": parsed.slug,
            "name": parsed.name,
            "description": parsed.description,
            "target_environment": parsed.environment,
        },
    )


def _configure_case_replace(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-id", type=int, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases-file")
    source.add_argument("--stdin", action="store_true")


def _case_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    raw = sys.stdin.read() if parsed.stdin else Path(parsed.cases_file).read_text()
    cases = json.loads(raw)
    if not isinstance(cases, list):
        raise ValueError("cases input must be a JSON array")
    return {"plan_id": parsed.plan_id, "cases": cases}


def qa_plan_cases_replace(args: List[str]) -> int:
    usage = (
        "yoke qa plan-cases replace --project P --plan-id N "
        "(--cases-file PATH | --stdin) [--json]"
    )
    return _global(
        args,
        prog="yoke qa plan-cases replace",
        usage=usage,
        function_id="qa.plan_cases.replace",
        configure=_configure_case_replace,
        payload=_case_payload,
    )


def _configure_attachment(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--plan-id", type=int, required=True)
    parser.add_argument("--transition", required=True)
    parser.add_argument("--qa-phase", default="verification")


def qa_plan_item_attach(args: List[str]) -> int:
    usage = (
        "yoke qa item-plan attach --item PREFIX-N --project P --plan-id N "
        "--transition T [--qa-phase PHASE] [--json]"
    )
    parser = argparse.ArgumentParser(prog="yoke qa item-plan attach", description=usage)
    parser.add_argument("--item", required=True)
    parser.add_argument("--project", required=True)
    _configure_attachment(parser)
    add_session_arg(parser)
    add_json_arg(parser)
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
    "qa_plan_create",
    "qa_plan_get",
    "qa_plan_item_attach",
    "qa_plan_list",
    "qa_plan_materialize_for_item",
    "qa_plan_rematerialize",
]
