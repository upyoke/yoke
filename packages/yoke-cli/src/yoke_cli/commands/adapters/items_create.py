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
from yoke_cli.commands.adapters.items_create_text import resolve_create_text
from yoke_cli.commands.adapters.dash_verification_plan import (
    resolve_dash_verification_plan,
    DashVerificationPlanError,
)
from yoke_contracts.api.function_call import TargetRef

ITEMS_CREATE_USAGE = (
    "yoke items create (TITLE | --title-file PATH) WORKFLOW "
    "(--spec-file PATH | --stdin) --execution-instructions-considered "
    "[--project P] [--priority P] [--entry-surface SURFACE] [--dry-run] [--json]"
)


def items_create(args: list[str], *, shortcut: str | None = None) -> int:
    command = f"yoke {shortcut}" if shortcut else "yoke items create"
    if any(arg.split("=", 1)[0] == "--content-file" for arg in args):
        return usage_error(
            "ITEM_TEXT_FLAG_RETIRED: use --title-file PATH for title "
            "and --spec-file PATH or --stdin for spec"
        )
    usage = (
        f"{command} (TITLE | --title-file PATH) "
        "(SPEC | --spec-file PATH | --stdin) --execution-instructions-considered"
        if shortcut
        else ITEMS_CREATE_USAGE
    )
    parser = argparse.ArgumentParser(
        prog=command,
        description=usage + "\n\n"
        "task  Laneless, merge-free work in projects without a code repository.\n"
        "dash  Focused repository work with a lane or selected gates;\n"
        "      code project work -> yoke dash (Task refuses there).\n"
        "idea  Use /yoke idea for planned intake and scaffolding.\n"
        "Every item is created with its spec: the agreed outcome.\n"
        "First: yoke workflow execution-instruction resolve --workflow W --project P --full\n"
        "pass --execution-instructions-considered after reading them.",
    )
    parser.add_argument(
        "title",
        nargs="?",
        metavar="TITLE",
        help="Title; use --title-file PATH for a file.",
    )
    parser.add_argument(
        "spec" if shortcut else "workflow",
        nargs="?",
        metavar="SPEC" if shortcut else "WORKFLOW",
        help="Spec text." if shortcut else "Workflow id.",
    )
    parser.add_argument("--title-file", help="Read title from this UTF-8 file.")
    parser.add_argument("--spec-file", help="Read spec from this UTF-8 file.")
    parser.add_argument("--stdin", action="store_true", help="Read spec from stdin.")
    parser.add_argument(
        "--priority",
        choices=("high", "medium", "low"),
        help="Priority bucket: high, medium, or low.",
    )
    parser.add_argument(
        "--project", help="Project slug/id, defaulting to the mapped checkout."
    )
    parser.add_argument(
        "--deployment-flow",
        metavar="FLOW",
        help="Use yoke deployment-flows list --project P to choose.",
    )
    parser.add_argument(
        "--status", help="Initial stage, defaulting to the workflow first stage."
    )
    parser.add_argument(
        "--source", help="Numeric source actor, defaulting to the authenticated actor."
    )
    parser.add_argument("--owner", help="Numeric owner actor, defaulting to source.")
    parser.add_argument(
        "--strategy-doc",
        help="Link the item to this project strategy document at creation.",
    )
    parser.add_argument(
        "--entry-surface",
        choices=("cli", "harness_skill", "promotion", "web_form"),
        help="Filer-owned provenance: skills pass harness_skill; Task/Dash default "
        "to cli. This flag grants no caller or workflow authority.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without a row or GitHub mirror."
    )
    parser.add_argument(
        "--execution-instructions-considered",
        action="store_true",
        help="Attest the applicable workflow execution instructions were read first.",
    )
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument("--verification-plan", metavar="ID_OR_SLUG")
    verification.add_argument("--verification-method")
    for flag in ("path-claims", "approval-on-done", "deployment"):
        parser.add_argument(f"--{flag}", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        title, workflow, spec = resolve_create_text(parsed, shortcut)
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
