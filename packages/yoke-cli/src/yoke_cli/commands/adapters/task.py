"""Laneless Task filing adapter."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.dash_file import DASH_PRIORITY_CHOICES
from yoke_contracts.api.function_call import TargetRef


TASK_FILE_USAGE = (
    "yoke task TITLE INSTRUCTION --execution-instructions-considered "
    "[--project P] [--priority P] "
    "[--verification-plan ID_OR_SLUG | --verification-method ID] "
    "[--path-claims] [--approval-on-done] [--deployment] "
    "[--strategy-doc SLUG] [--session-id S] [--json]"
)

TASK_HELP = """File one laneless, merge-free Task through items.create.

Examples:
  yoke workflow execution-instruction resolve --workflow task --project acme
  yoke task "Refresh inventory" "Refresh the local inventory file." \
    --project acme --execution-instructions-considered

Choose the filing surface:
  task  Laneless, merge-free work whose observed changes need a floor attestation.
  dash  Focused repository work that needs a git lane or an optional gate.
  idea  Use /yoke idea for Issue, Epic, or Blitz intake and planning structure.

Task v1 exposes no item-posture knobs. The Dash posture flags are parsed only
so this command can refuse them with a named reason and the exact alternative.
"""

TASK_VERIFICATION_REFUSAL = (
    "TASK_VERIFICATION_POSTURE_UNSUPPORTED: task v1 has no verification "
    "posture or review stage. File work needing a selected verification plan "
    "or method with yoke dash TITLE INSTRUCTION."
)
TASK_PATH_CLAIMS_REFUSAL = (
    "TASK_PATH_CLAIMS_POSTURE_UNSUPPORTED: task v1 does not allow a path-claims "
    "posture. File repository work needing reserved paths with yoke dash "
    "TITLE INSTRUCTION."
)
TASK_APPROVAL_REFUSAL = (
    "TASK_APPROVAL_POSTURE_UNSUPPORTED: approval-gated postures are Dash-only "
    "today; task v1 declares approvals=none and no item posture allowlist. "
    "File approval-gated work with yoke dash TITLE INSTRUCTION. Task approval "
    "gates await the approvals, notifications, and inbox design."
)
TASK_DEPLOYMENT_REFUSAL = (
    "TASK_DEPLOYMENT_POSTURE_UNSUPPORTED: task v1 is merge-free and has no "
    "deploy-after-merge posture. File work needing item-bound delivery with "
    "yoke dash TITLE INSTRUCTION."
)


def _unsupported_posture(parsed: argparse.Namespace) -> Optional[str]:
    if parsed.verification_plan is not None or parsed.verification_method:
        return TASK_VERIFICATION_REFUSAL
    if parsed.path_claims:
        return TASK_PATH_CLAIMS_REFUSAL
    if parsed.approval_on_done:
        return TASK_APPROVAL_REFUSAL
    if parsed.deployment:
        return TASK_DEPLOYMENT_REFUSAL
    return None


def task_file(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke task",
        description=TASK_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
            "Strategy document this Task belongs to; makes it a member of "
            "that document's steering scope from the moment it is filed."
        ),
    )
    parser.add_argument("--path-claims", action="store_true")
    parser.add_argument("--approval-on-done", action="store_true")
    parser.add_argument("--deployment", action="store_true")
    parser.add_argument(
        "--execution-instructions-considered",
        dest="execution_instructions_considered",
        action="store_true",
        help=(
            "Attest that this filer retrieved the operator execution "
            "instructions for the task workflow and project first."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, TASK_FILE_USAGE)
    if parsed is None:
        return 2
    refusal = _unsupported_posture(parsed)
    if refusal is not None:
        return usage_error(refusal)

    project = client_project_context(parsed.project)
    payload: Dict[str, Any] = {
        "title": parsed.title,
        "instruction": parsed.instruction,
        "workflow": "task",
        "entry_surface": "cli",
        "workflow_posture": {},
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


__all__ = [
    "TASK_APPROVAL_REFUSAL",
    "TASK_DEPLOYMENT_REFUSAL",
    "TASK_FILE_USAGE",
    "TASK_HELP",
    "TASK_PATH_CLAIMS_REFUSAL",
    "TASK_VERIFICATION_REFUSAL",
    "task_file",
]
