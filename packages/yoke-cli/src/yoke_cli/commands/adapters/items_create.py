"""``yoke items create`` flag adapter — sanctioned idea-intake item create.

Wraps the ``items.create`` function id. ``--idea-intake`` is the
function-call-surface equivalent of the local ``YOKE_IDEA_INTAKE=1``
env var: it threads ``provenance="idea"`` so the create passes the
``ticket_intake_provenance`` gate. ``/yoke idea`` is the only
sanctioned caller; a bare ``yoke items create`` without ``--idea-intake``
is rejected with a recovery hint that names ``/yoke idea``.

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
    "yoke items create TITLE TYPE [--priority P] [--project NAME] "
    "[--deployment-flow FLOW] [--status STATUS] [--source ACTOR] "
    "[--owner ACTOR] [--idea-intake] [--dry-run] [--session-id S] [--json]"
)


def items_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items create", description=ITEMS_CREATE_USAGE,
    )
    parser.add_argument("title", help="Item title (<=100 chars).")
    parser.add_argument("type", help="Item type: issue | epic.")
    parser.add_argument("--priority", default=None,
                        help="Priority bucket; defaults to the project default.")
    parser.add_argument(
        "--project", default=None,
        help="Project slug/id (default: the checkout's mapped project).",
    )
    parser.add_argument("--deployment-flow", dest="deployment_flow", default=None,
                        help="Deployment flow id.")
    parser.add_argument("--status", default="idea",
                        help="Initial status (idea intake is always 'idea').")
    parser.add_argument("--source", default=None,
                        help="Numeric source actor id (default: authenticated/session actor).")
    parser.add_argument("--owner", default=None,
                        help="Numeric owner actor id (default: source actor).")
    parser.add_argument(
        "--idea-intake", dest="idea_intake", action="store_true",
        help="Mark this as sanctioned /yoke idea intake (sets provenance='idea').",
    )
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Preview only; no row created, no GitHub sync.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_CREATE_USAGE)
    if parsed is None:
        return 2

    payload: Dict[str, Any] = {
        "title": parsed.title,
        "type": parsed.type,
        "status": parsed.status,
        "dry_run": bool(parsed.dry_run),
    }
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
    if parsed.idea_intake:
        payload["provenance"] = "idea"

    return dispatch_and_emit(
        function_id="items.create",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
