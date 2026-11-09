"""Sectioned human view of the workflow registry; machine data stays intact."""

from __future__ import annotations

import re
import shlex
import textwrap

from yoke_cli.transport.human_values import write_human
from yoke_cli.transport.output_limit import (
    full_output_requested,
    requested_section,
    section_command,
)


def write_workflows_definition(response, stdout, stderr) -> None:
    result = response.result or {}
    if not full_output_requested() and requested_section() is None:
        _write_roster(result, stdout)
        return
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


def _details(heading: str) -> str:
    return section_command(heading) or shlex.join(
        ["yoke", "workflows", "definition", "get", "--section", heading]
    )


def _description(workflow: dict) -> str:
    text = " ".join((workflow.get("description") or "").split())
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return textwrap.shorten(sentence, width=80, placeholder="…")


def _write_roster(result: dict, stdout) -> None:
    print("## Workflows\nid  version  description", file=stdout)
    for workflow in result.get("workflows") or []:
        print(
            f"{workflow['id']}  {workflow.get('current_version')}  "
            f"{_description(workflow)}",
            file=stdout,
        )
        print(f"Details: {_details(workflow['id'])}", file=stdout)
    gates = result.get("gate_catalog") or []
    print(
        f"\n## Gate catalog\n{len(gates)} gates. "
        f"Details: {_details('Gate catalog')}",
        file=stdout,
    )
    flows = result.get("flows") or []
    active = [flow for flow in flows if flow.get("status") == "active"]
    print(
        f"\n## Deployment flows ({len(active)} active of {len(flows)})",
        file=stdout,
    )
    for flow in active:
        print(f"{flow['name']}  {flow.get('target_environment') or 'unspecified'}", file=stdout)
    print(
        f"{len(flows) - len(active)} disabled flows hidden. "
        f"All flows: {_details('Flows')}",
        file=stdout,
    )
