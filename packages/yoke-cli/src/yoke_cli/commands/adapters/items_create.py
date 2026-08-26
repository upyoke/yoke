"""``yoke items create`` workflow-selected creation adapter.

Wraps the ``items.create`` function id. Callers name the workflow and the
typed entry surface through which they are creating it.

Same envelope over both transports: a local universe dispatches
in-process, and an https connection POSTs the same
``FunctionCallRequest`` to ``/v1/functions/call`` — which is what makes
``/yoke idea`` work against a prod-https control plane.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = ["items_create", "ITEMS_CREATE_USAGE"]


ITEMS_CREATE_USAGE = (
    "yoke items create TITLE [WORKFLOW] --execution-instructions-considered "
    "[--priority P] [--project NAME] "
    "[--deployment-flow FLOW] [--status STATUS] [--source ACTOR] "
    "[--owner ACTOR] [--entry-surface SURFACE] [--dry-run] "
    "[--session-id S] [--json]"
)


def items_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items create", description=ITEMS_CREATE_USAGE,
    )
    parser.add_argument("title", help="Item title (<=100 chars).")
    parser.add_argument(
        "workflow", nargs="?", default=None,
        help="Workflow id; temporarily defaults to issue.",
    )
    parser.add_argument("--priority", default=None,
                        help="Priority bucket; defaults to the project default.")
    parser.add_argument(
        "--project", default=None,
        help="Project slug/id (default: the checkout's mapped project).",
    )
    parser.add_argument("--deployment-flow", dest="deployment_flow", default=None,
                        help="Deployment flow id.")
    parser.add_argument(
        "--status", default=None,
        help="Initial stage; defaults to the workflow's first stage.",
    )
    parser.add_argument("--source", default=None,
                        help="Numeric source actor id (default: authenticated/session actor).")
    parser.add_argument("--owner", default=None,
                        help="Numeric owner actor id (default: source actor).")
    parser.add_argument(
        "--entry-surface",
        choices=("cli", "harness_skill", "promotion", "web_form"),
        default=None,
        help="Typed creation surface allowed by the workflow.",
    )
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Preview only; no row created, no GitHub sync.")
    parser.add_argument(
        "--execution-instructions-considered",
        dest="execution_instructions_considered",
        action="store_true",
        help=(
            "Attest that this filer retrieved the operator execution "
            "instructions for this workflow and project first (yoke "
            "workflow execution-instruction resolve). Required for "
            "this surface."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_CREATE_USAGE)
    if parsed is None:
        return 2

    payload: Dict[str, Any] = {
        "title": parsed.title,
        "dry_run": bool(parsed.dry_run),
        # Passed through, never inferred: the flag attests what the filer
        # did before authoring, which this adapter cannot observe.
        "execution_instructions_considered": bool(
            parsed.execution_instructions_considered
        ),
    }
    if parsed.workflow is not None:
        payload["workflow"] = parsed.workflow
    if parsed.status is not None:
        payload["status"] = parsed.status
    if parsed.priority is not None:
        payload["priority"] = parsed.priority
    project = client_project_context(parsed.project)
    if project is not None:
        payload["project"] = project
    if parsed.deployment_flow is not None:
        payload["deployment_flow"] = parsed.deployment_flow
    if parsed.source is not None:
        payload["source"] = parsed.source
    if parsed.owner is not None:
        payload["owner"] = parsed.owner
    if parsed.entry_surface is not None:
        payload["entry_surface"] = parsed.entry_surface

    return dispatch_and_emit(
        function_id="items.create",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
