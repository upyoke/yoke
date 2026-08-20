"""Doctor HC: this project's hosted deploy routes carry their release contract.

A route that dispatches a GitHub Actions workflow participates in a
contract the runtime depends on but cannot repair at run time:

* the dispatch carries an opaque correlation marker, so a lost dispatch
  response can still be reconciled to the exact workflow run;
* the dispatch resolves its target environment from the run's typed
  environment reference rather than a hardcoded label, so the same
  definition serves every environment it is pointed at;
* the dispatch neither reuses an older CI result for the same commit nor
  re-waits on CI the verification gate already proved; and
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

from yoke_core.domain.db_helpers import query_rows
import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-hosted-route-stage-contract"
HC_DESC = "Hosted deploy routes carry their release contract"

DISPATCH_RUNNER = "github-actions-workflow"
WARM_UP_RUNNER = "warm-up"
CORRELATION_INPUT = "yoke_dispatch_id"
TARGET_ENVIRONMENT_PLACEHOLDER = "{target_environment}"


def _active_flow_stages(conn, project: str) -> Dict[str, List[Any]]:
    """Return ``{flow_id: stages}`` for the project's active flows."""
    rows = query_rows(
        conn,
        "SELECT f.id, f.stages FROM deployment_flows f "
        "JOIN projects p ON p.id = f.project_id "
        "WHERE p.slug=%s AND f.status='active'",
        (project,),
    )
    flows: Dict[str, List[Any]] = {}
    for row in rows:
        flow_id = str(row["id"] if hasattr(row, "keys") else row[0])
        raw = row["stages"] if hasattr(row, "keys") else row[1]
        try:
            stages = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            stages = None
        if isinstance(stages, list):
            flows[flow_id] = stages
    return flows


def _route_violations(flow_id: str, stages: List[Any]) -> List[str]:
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
        if stage.get("wait_for_ci") is not False:
            problems.append(
                f"stage '{name}' waits on CI for a commit the gate already "
                "proved (wait_for_ci is not false)"
            )
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
    else:
        warm = stages[runners.index(WARM_UP_RUNNER)]
        if not warm.get("connection_env"):
            problems.append("warm-up stage names no connection_env to warm")
    return [f"- `{flow_id}` {problem}" for problem in problems]


def hc_hosted_route_stage_contract(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-hosted-route-stage-contract: hosted routes carry their contract."""
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record(
            HC_NAME, HC_DESC, "PASS",
            "deployment_flows table not present, skipping",
        )
        return
    flows = _active_flow_stages(conn, args.project)
    dispatching = {
        flow_id: stages
        for flow_id, stages in flows.items()
        if any(
            isinstance(stage, dict)
            and stage.get("step_runner") == DISPATCH_RUNNER
            for stage in stages
        )
    }
    if not dispatching:
        rec.record(
            HC_NAME, HC_DESC, "PASS",
            f"'{args.project}' declares no active workflow-dispatching route",
        )
        return
    findings: List[str] = []
    for flow_id in sorted(dispatching):
        findings.extend(_route_violations(flow_id, dispatching[flow_id]))
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
        "correlation marker, the target-environment placeholder, fresh CI "
        "reconciliation, and a warm-up after the roll",
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
