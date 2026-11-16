"""Doctor HC: this project's hosted deploy routes carry their release contract.

A route that dispatches a GitHub Actions workflow participates in a
contract the runtime depends on but cannot repair at run time:

* the dispatch carries an opaque correlation marker, so a lost dispatch
  response can still be reconciled to the exact workflow run;
* the dispatch resolves its target environment from the run's typed
  environment reference rather than a hardcoded label, so the same
  definition serves every environment it is pointed at;
* normal production dispatches wait for per-commit CI; Stage relies on
  the paired production gate and hotfix routes may skip it deliberately; and
* the route warms the box it just rolled, after it rolls it, so the first
  heavy call after a release is not the operator's.

Flow definitions are ordinary database rows written by
``yoke deployment-flows create`` and retired by
``yoke deployment-flows set-status <flow-id> disabled``. Nothing re-reads
them at write time, so the live rows are what this check reads.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from yoke_core.domain.control_plane_transport import relay
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-hosted-route-stage-contract"
HC_DESC = "Hosted deploy routes carry their release contract"

DISPATCH_RUNNER = "github-actions-workflow"
WARM_UP_RUNNER = "warm-up"
CORRELATION_INPUT = "yoke_dispatch_id"
TARGET_ENVIRONMENT_PLACEHOLDER = "{target_environment}"


def _active_flows(project: str) -> List[dict]:
    """Use the CLI's registered read on both HTTPS and database clients."""
    result = relay("deployment_flows.list", {"project": project})
    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ValueError("deployment_flows.list returned no rows list")
    flows = []
    for row in rows:
        flow = dict(row)
        raw = flow["stages"]
        stages = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(stages, list):
            raise ValueError(f"flow {flow['id']!r} stages are not a list")
        flow["stages"] = stages
        flows.append(flow)
    return flows


def _production_environments(project: str, flows: List[dict]) -> Dict[str, bool]:
    roles = {}
    for flow in flows:
        environment = flow.get("target_environment")
        if not environment:
            raise ValueError(f"dispatching flow {flow['id']!r} has no target_environment")
        if environment in roles:
            continue
        result = relay("projects.environment_settings.get", {
            "project": project, "environment": environment,
            "paths": ["role.production"],
        })
        production = result.get("values", {}).get("role.production")
        if not isinstance(production, bool):
            raise ValueError(
                f"environment {environment!r} has no boolean role.production"
            )
        roles[environment] = production
    return roles


def _route_violations(
    flow_id: str, stages: List[Any], *, production: bool,
) -> List[str]:
    runners = [
        str(stage.get("step_runner", ""))
        for stage in stages
        if isinstance(stage, dict)
    ]
    if DISPATCH_RUNNER not in runners:
        return []
    problems: List[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("step_runner") != DISPATCH_RUNNER:
            continue
        name = stage.get("name", "?")
        if stage.get("dispatch_correlation_input") != CORRELATION_INPUT:
            problems.append(
                f"stage '{name}' does not set "
                f"dispatch_correlation_input={CORRELATION_INPUT}"
            )
        if stage.get("reconcile_by_head_sha") is not False:
            problems.append(
                f"stage '{name}' may reuse an older run for the same commit "
                "(reconcile_by_head_sha is not false)"
            )
        hotfix = (stage.get("inputs") or {}).get("release_mode") == "hotfix"
        if production and not hotfix and stage.get("wait_for_ci") is not True:
            problems.append(
                f"stage '{name}' omits the production per-commit CI gate "
                "(wait_for_ci is not true)"
            )
        elif not isinstance(stage.get("wait_for_ci"), bool):
            problems.append(f"stage '{name}' must declare boolean wait_for_ci")
        target = (stage.get("inputs") or {}).get("target_environment")
        if target != TARGET_ENVIRONMENT_PLACEHOLDER:
            problems.append(
                f"stage '{name}' passes target_environment={target!r} instead "
                f"of the {TARGET_ENVIRONMENT_PLACEHOLDER} placeholder"
            )
    if WARM_UP_RUNNER not in runners:
        problems.append("route never warms the box it rolls")
    elif runners.index(WARM_UP_RUNNER) < runners.index(DISPATCH_RUNNER):
        problems.append("route warms before it rolls")
    # Omitted warm-up connection_env follows the run target's declared
    # deploy.serving_connection; an explicit value still works.
    return [f"- `{flow_id}` {problem}" for problem in problems]


def hc_hosted_route_stage_contract(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-hosted-route-stage-contract: hosted routes carry their contract."""
    try:
        flows = _active_flows(args.project)
        dispatching = [
            flow for flow in flows
            if any(
                isinstance(stage, dict)
                and stage.get("step_runner") == DISPATCH_RUNNER
                for stage in flow["stages"]
            )
        ]
        production = _production_environments(args.project, dispatching)
    except Exception as exc:  # noqa: BLE001 - unreadable authority is a failure
        rec.record(HC_NAME, HC_DESC, "FAIL", compose_refusal(
            f"Hosted-route contract cannot be evaluated: {exc}",
            recovery=("Run `yoke deployment-flows list --project "
                      f"{args.project}` and `yoke projects environment-settings "
                      f"get --project {args.project} --environment NAME "
                      "--path role.production`; repair the named read or declaration, "
                      "then rerun this check."),
        ))
        return
    if not dispatching:
        rec.record(
            HC_NAME, HC_DESC, "PASS",
            f"'{args.project}' declares no active workflow-dispatching route",
        )
        return
    findings: List[str] = []
    for flow in sorted(dispatching, key=lambda flow: flow["id"]):
        findings.extend(_route_violations(
            flow["id"], flow["stages"],
            production=production[flow["target_environment"]],
        ))
    if findings:
        head = (
            f"- {len(findings)} hosted-route contract violation(s) across "
            f"{len(dispatching)} active dispatching route(s). Retire the "
            "definition and create its replacement: "
            "`yoke deployment-flows set-status <flow-id> disabled` then "
            "`yoke deployment-flows create <flow-id> --project "
            f"{args.project} --name NAME --stages-file PATH`."
        )
        rec.record(HC_NAME, HC_DESC, "FAIL", "\n".join([head, ""] + findings))
        return
    rec.record(
        HC_NAME, HC_DESC, "PASS",
        f"{len(dispatching)} active dispatching route(s) carry the "
        "correlation marker, the target-environment placeholder, the production "
        "per-commit CI gate (with Stage/hotfix exceptions), and warm-up after the roll",
    )


__all__ = [
    "CORRELATION_INPUT",
    "DISPATCH_RUNNER",
    "HC_DESC",
    "HC_NAME",
    "TARGET_ENVIRONMENT_PLACEHOLDER",
    "WARM_UP_RUNNER",
    "hc_hosted_route_stage_contract",
]

from yoke_project_checks._declare import self_project_checks  # noqa: E402

PROJECT_HEALTH_CHECKS = self_project_checks(
    (
        'hosted-route-stage-contract',
        'Hosted deploy routes carry their release contract',
        hc_hosted_route_stage_contract,
    ),
)
