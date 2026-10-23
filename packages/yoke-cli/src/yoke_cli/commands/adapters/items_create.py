"""One workflow-selected item filing command and its thin shortcuts."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.items_create_dispatch import dispatch_create
from yoke_cli.commands.adapters.items_create_policy import (
    refuse_unscaffolded_create,
    _unsupported_posture,
)
from yoke_cli.commands.adapters.items_create_text import (
    add_create_text_args,
    resolve_create_text,
)
from yoke_cli.commands.adapters.dash_verification_plan import (
    resolve_dash_verification_plan,
    DashVerificationPlanError,
)
from yoke_contracts.api.function_call import TargetRef

_CREATE_OPTIONS_USAGE = (
    "[--project P] [--priority high|medium|low] [--status STAGE] "
    "[--deployment-flow FLOW] [--source N] [--owner N] [--strategy-doc SLUG] "
    "[--entry-surface SURFACE] "
    "[--verification-plan ID_OR_SLUG | --verification-method METHOD] "
    "[--path-claims] [--approval-on-done] [--deployment] [--dry-run] "
    "[--session-id S] [--json]"
)
ITEMS_CREATE_USAGE = (
    "yoke items create (--title TEXT | --title-file PATH) --workflow W "
    "(--spec-file PATH | --stdin) --execution-instructions-considered "
    + _CREATE_OPTIONS_USAGE
)


def items_create(args: list[str], *, shortcut: str | None = None) -> int:
    command = f"yoke {shortcut}" if shortcut else "yoke items create"
    if any(arg.split("=", 1)[0] == "--content-file" for arg in args):
        return usage_error(
            "ITEM_TEXT_FLAG_RETIRED: use --title-file PATH for title "
            "and --spec-file PATH or --stdin for spec"
        )
    usage = (
        f"{command} (--title TEXT | --title-file PATH) "
        "(--spec-file PATH | --stdin) --execution-instructions-considered "
        + _CREATE_OPTIONS_USAGE
        if shortcut
        else ITEMS_CREATE_USAGE
    )
    parser = argparse.ArgumentParser(
        prog=command,
        allow_abbrev=False,
        usage=usage,
        description="task  Laneless, merge-free work in projects without a code repository.\n"
        "dash  Focused repository work with a lane or selected gates;\n"
        "      code project work -> yoke dash (Task refuses there).\n"
        "idea  Use /yoke idea for planned intake and scaffolding.\n"
        "Every item is created with its spec: the agreed outcome.\n"
        "First: yoke workflow execution-instruction resolve --workflow W --project P --full\n"
        "pass --execution-instructions-considered after reading them.",
    )
    add_create_text_args(parser)
    if not shortcut:
        parser.add_argument("--workflow", metavar="W", help="Workflow id.")
    parser.add_argument(
        "--priority",
        choices=("high", "medium", "low"),
        metavar="high|medium|low",
        help="Priority bucket: high, medium, or low.",
    )
    parser.add_argument(
        "--project",
        metavar="P",
        help="Project slug or id (default: the checkout's mapped project).",
    )
    parser.add_argument(
        "--deployment-flow",
        metavar="FLOW",
        help=(
            "Deployment flow for the item; list the choices with "
            "yoke deployment-flows list --project P."
        ),
    )
    parser.add_argument(
        "--status",
        metavar="STAGE",
        help="Starting stage (default: the workflow's first stage).",
    )
    parser.add_argument(
        "--source",
        metavar="N",
        help="Actor id that filed the item (default: the signed-in actor).",
    )
    parser.add_argument(
        "--owner", metavar="N", help="Actor id that owns the item (default: --source)."
    )
    parser.add_argument(
        "--strategy-doc",
        metavar="SLUG",
        help="Link the item to this project strategy document at creation. To "
        "move an existing item to another document later, run `yoke strategy "
        "execution link ITEM --project P --slug SLUG`.",
    )
    parser.add_argument(
        "--entry-surface",
        choices=("cli", "harness_skill", "promotion", "web_form"),
        metavar="SURFACE",
        help="Where the filing came from: cli, harness_skill, promotion, or "
        "web_form. Skills pass harness_skill; task and dash default to cli. "
        "It grants no extra authority.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without saving the item or mirroring "
        "it to GitHub.",
    )
    parser.add_argument(
        "--execution-instructions-considered",
        action="store_true",
        help="Confirm you read the workflow's execution instructions first.",
    )
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument(
        "--verification-plan",
        metavar="ID_OR_SLUG",
        help="Verify the item with this saved verification plan.",
    )
    verification.add_argument(
        "--verification-method",
        metavar="METHOD",
        help="Verify the item with this ad hoc method id.",
    )
    posture_help = {
        "path-claims": "Reserve repository paths before work (Dash only).",
        "approval-on-done": "Require approval before the item is done (Dash only).",
        "deployment": "Deploy the item after it merges (Dash only).",
    }
    for flag, flag_help in posture_help.items():
        parser.add_argument(f"--{flag}", action="store_true", help=flag_help)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        title, workflow, spec = resolve_create_text(parsed, shortcut, command)
    except ValueError as exc:
        return usage_error(str(exc))
    refused = refuse_unscaffolded_create(
        dry_run=parsed.dry_run,
        workflow=workflow,
        entry_surface=parsed.entry_surface,
    )
    if refused is not None:
        return refused
    if workflow == "task":
        refusal = _unsupported_posture(parsed)
        if refusal:
            return usage_error(refusal)
    project = client_project_context(parsed.project)
    posture = {}
    if parsed.verification_plan is not None:
        try:
            posture["verification"] = {
                "kind": "plan",
                "plan_id": resolve_dash_verification_plan(
                    parsed.verification_plan,
                    project=project,
                    session_id=parsed.session_id,
                ),
            }
        except DashVerificationPlanError as exc:
            return usage_error(str(exc))
    if parsed.verification_method:
        posture["verification"] = {
            "kind": "ad_hoc",
            "method_id": parsed.verification_method,
        }
    for key in ("path_claims", "approval_on_done", "deployment"):
        if getattr(parsed, key):
            posture[key] = True
    payload = {
        "title": title,
        "workflow": workflow,
        "spec": spec,
        "dry_run": parsed.dry_run,
        "execution_instructions_considered": parsed.execution_instructions_considered,
    }
    if workflow in ("dash", "task") or posture:
        payload["workflow_posture"] = posture
    for key in (
        "status",
        "priority",
        "deployment_flow",
        "source",
        "owner",
        "strategy_doc",
    ):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if project is not None:
        payload["project"] = project
    surface = parsed.entry_surface or ("cli" if workflow in ("dash", "task") else None)
    if surface is not None:
        payload["entry_surface"] = surface
    return dispatch_create(
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
