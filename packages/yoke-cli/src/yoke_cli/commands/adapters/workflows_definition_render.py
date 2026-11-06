"""Sectioned human view of the workflow registry; machine data stays intact."""

from __future__ import annotations

import shlex

from yoke_cli.transport.human_values import write_human
from yoke_cli.transport.output_limit import full_output_requested


def write_workflows_definition(response, stdout, stderr) -> None:
    result = response.result or {}
    write_human(
        {
            key: value
            for key, value in result.items()
            if key not in {"workflows", "gate_catalog", "flows"}
        },
        stdout,
    )
    for workflow in result.get("workflows") or []:
        workflow_id = workflow["id"]
        print(f"\n## {workflow_id}", file=stdout)
        if full_output_requested():
            write_human(workflow, stdout)
            continue
        write_human(
            {key: value for key, value in workflow.items() if key != "versions"},
            stdout,
        )
        versions = workflow.get("versions") or []
        command = shlex.join(["yoke", "workflows", "version", "list", workflow_id])
        print(
            f"{len(versions)} versions, current {workflow.get('current_version')} "
            f"(see `{command}`)",
            file=stdout,
        )
    print("\n## Gate catalog", file=stdout)
    write_human(result.get("gate_catalog") or [], stdout)
    print("\n## Flows", file=stdout)
    for flow in result.get("flows") or []:
        print(f"\n### {flow['name']}", file=stdout)
        write_human(flow, stdout)
