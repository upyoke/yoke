"""``yoke deployment-flows create`` adapter.

Flows are ordinary database objects: this command defines one, and
``yoke deployment-flows set-status FLOW-ID disabled`` retires one. A
definition a deployment run has referenced stays immutable, so retiring
and replacing is how a route changes shape.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.api.function_call import TargetRef


USAGE = (
    "yoke deployment-flows create FLOW-ID --project P --name NAME "
    "(--stages-json JSON | --stages-file PATH | --stdin) "
    "[--description TEXT] [--on-failure halt|continue] "
    "[--target-tier persistent|ephemeral] [--environment ENV] "
    "[--done-description TEXT] [--status active|disabled] "
    "[--session-id S] [--json]"
)

EPILOG = """\
Examples:
  # A merge-only flow with no deploy target.
  yoke deployment-flows create acme-internal --project acme \\
    --name "Acme internal" --stages-file stages.json

  # A flow that deploys to the registered `prod` environment.
  yoke deployment-flows create acme-prod --project acme \\
    --name "Acme production" --stages-file stages.json \\
    --target-tier persistent --environment prod

  # Retire a flow that a run already referenced (its definition is immutable).
  yoke deployment-flows set-status acme-prod disabled

A persistent flow names exactly one registered environment; an ephemeral
flow deploys per-run preview substrate and names none; a merge-only flow
declares neither.
"""


def deployment_flows_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows create",
        description="Define one deployment flow for a project.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("flow_id")
    parser.add_argument("--project", required=True)
    parser.add_argument("--name", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group, "--stages-json", "--stages-file", dest="stages_json",
    )
    group.add_argument("--stdin", action="store_true", help="Read stage JSON.")
    parser.add_argument("--description", default="")
    parser.add_argument("--on-failure", default="halt")
    parser.add_argument(
        "--target-tier", choices=("persistent", "ephemeral"), default=None,
    )
    parser.add_argument("--environment", default=None)
    parser.add_argument("--done-description", default=None)
    parser.add_argument(
        "--status", choices=("active", "disabled"), default="active",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    if parsed.stdin:
        stages = sys.stdin.read()
    else:
        try:
            stages = resolve_text_file(
                parsed.stages_json, parsed.stages_json_file, "--stages-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("message", ""), file=stdout)

    payload = {
        "flow_id": parsed.flow_id,
        "name": parsed.name,
        "stages": stages,
        "description": parsed.description,
        "on_failure": parsed.on_failure,
        "target_tier": parsed.target_tier,
        "environment": parsed.environment,
        "done_description": parsed.done_description,
        "status": parsed.status,
    }
    return dispatch_and_emit(
        function_id="deployment_flows.create",
        target=TargetRef(kind="global", project_id=parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["USAGE", "deployment_flows_create"]
