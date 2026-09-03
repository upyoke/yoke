"""``yoke dash TITLE INSTRUCTION`` filing adapter.

Files one instruction-sized item through ``items.create``. Kept beside the
Dash execution adapters rather than inside them: filing is the only Dash
surface a plain terminal reaches, and it is the only one that names a
workflow, a posture, and a strategy document.
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
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.adapters.dash_verification_plan import (
    DashVerificationPlanError,
    resolve_dash_verification_plan,
)
from yoke_cli.commands.adapters.workflows_item_posture import (
    WORKFLOWS_ITEM_POSTURE_AMEND_HINT,
)

DASH_FILE_USAGE = (
    "yoke dash TITLE INSTRUCTION --execution-instructions-considered "
    "[--project P] [--priority P] "
    "[--verification-plan ID_OR_SLUG | --verification-method ID] [--path-claims] "
    "[--approval-on-done] [--deployment] [--strategy-doc SLUG] "
    "[--session-id S] [--json]"
)
DASH_PRIORITY_CHOICES = ("high", "medium", "low")


def dash_file(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke dash", description=DASH_FILE_USAGE)
    parser.add_argument("title")
    parser.add_argument("instruction")
    parser.add_argument("--project")
    parser.add_argument(
        "--priority",
        choices=DASH_PRIORITY_CHOICES,
        help="Priority bucket: high, medium, or low.",
    )
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument("--verification-plan", metavar="ID_OR_SLUG")
    verification.add_argument("--verification-method")
    parser.add_argument(
        "--strategy-doc",
        metavar="SLUG",
        help=(
            "Strategy document this Dash belongs to; makes it a member of "
            "that document's steering scope from the moment it is filed."
        ),
    )
    parser.add_argument("--path-claims", action="store_true")
    parser.add_argument("--approval-on-done", action="store_true")
    parser.add_argument("--deployment", action="store_true")
    # Posture here is a convenience, not a one-shot: an item filed without a
    # selection, or with the wrong one, is amended in place afterwards.
    parser.epilog = WORKFLOWS_ITEM_POSTURE_AMEND_HINT
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
    parsed = parse_or_usage_error(parser, args, DASH_FILE_USAGE)
    if parsed is None:
        return 2
    project = client_project_context(parsed.project)
    posture: Dict[str, Any] = {}
    if parsed.verification_plan is not None:
        try:
            plan_id = resolve_dash_verification_plan(
                parsed.verification_plan,
                project=project,
                session_id=parsed.session_id,
            )
        except DashVerificationPlanError as exc:
            return usage_error(str(exc))
        posture["verification"] = {
            "kind": "plan",
            "plan_id": plan_id,
        }
    if parsed.verification_method:
        posture["verification"] = {
            "kind": "ad_hoc",
            "method_id": parsed.verification_method,
        }
    for key in ("path_claims", "approval_on_done", "deployment"):
        if getattr(parsed, key):
            posture[key] = True
    payload: Dict[str, Any] = {
        "title": parsed.title,
        "instruction": parsed.instruction,
        "workflow": "dash",
        "entry_surface": "cli",
        "workflow_posture": posture,
        # Passed through, never inferred: the flag attests what the filer
        # did before authoring, which this adapter cannot observe.
        "execution_instructions_considered": (
            parsed.execution_instructions_considered
        ),
    }
    if project is not None:
        payload["project"] = project
    if parsed.priority:
        payload["priority"] = parsed.priority
    if parsed.strategy_doc:
        payload["strategy_doc"] = parsed.strategy_doc
    return dispatch_and_emit(
        function_id="items.create",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )



__all__ = ["DASH_FILE_USAGE", "DASH_PRIORITY_CHOICES", "dash_file"]
