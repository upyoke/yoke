"""Reversible project retirement adapters."""

from __future__ import annotations

import argparse
from yoke_cli.command_hints import _with_env

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.transport.human_values import write_human
from yoke_contracts.api.function_call import TargetRef

USAGE_BY_FUNCTION_ID = {
    "projects.retire": (
        "yoke projects retire --project P --reason TEXT [--json] [--session-id S]"
    ),
    "projects.unretire": (
        "yoke projects unretire --project P [--json] [--session-id S]"
    ),
}


def _run(args, *, retired):
    verb = "retire" if retired else "unretire"
    usage = USAGE_BY_FUNCTION_ID[f"projects.{verb}"]
    parser = argparse.ArgumentParser(
        prog=f"yoke projects {verb}",
        description="Hide or restore a project without deleting anything. Retire "
        "also switches off what the project leaves running: it disables its "
        "active deployment flows, sets GitHub issue sync to disabled and marks "
        "its GitHub repository binding unavailable. It deletes nothing, and "
        "prints what stays attached with a count per kind: stored credentials "
        "(capability secret names, never values) first, then capability "
        "settings, the binding, flows, environments, sites, Pack records, QA "
        "plans and defaults, project roles and Pulumi stack state. Each kind "
        "names the existing command that removes or changes it, filled in for "
        "this project, or says that no command does. Retirement refuses open items, "
        "created/executing runs, and held claims; finish those obligations "
        "before retrying. The refusal names each held claim; a holder that "
        "ended keeps its claims until a steering-seat holder runs "
        "yoke claims work release --claim-id N --reason TEXT. "
        "Unretire restores visibility but re-enables no flow, sync or binding; "
        "it prints the command that re-enables each. "
        "Lists omit retired projects unless "
        "--include-retired is selected; direct project reads retain history.",
    )
    parser.add_argument("--project", required=True, help=f"Project to {verb}.")
    if retired:
        parser.add_argument("--reason", required=True, help="Why the project retires.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {"project": parsed.project}
    if retired:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id=f"projects.{verb}",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_result,
    )


def _write_result(response, stdout, stderr) -> None:
    """Print the summary, then each attachment and every re-enable command."""
    result = {k: v for k, v in (response.result or {}).items() if v is not None}
    attachments = result.pop("remaining_attachments", None)
    commands = result.pop("re_enable", None)
    note = result.pop("note", None)
    write_human(result, stdout)
    if attachments:
        print(
            "Still attached (retire deleted nothing; stored credentials first, "
            "names only):",
            file=stdout,
        )
        for entry in attachments:
            _write_attachment(entry, stdout)
    if note:
        print(note, file=stdout)
    if commands:
        print("re-enable:", file=stdout)
        for command in commands:
            print(f"  {_with_env(command)}", file=stdout)


def _write_attachment(entry, stdout) -> None:
    names = entry.get("names") or []
    suffix = f" ({', '.join(names)})" if names else ""
    print(f"  {entry['label']}: {entry['count']}{suffix}", file=stdout)
    for command in entry.get("commands") or []:
        print(f"    run: {_with_env(command)}", file=stdout)
    if entry.get("no_command"):
        print(f"    {entry['no_command']}", file=stdout)


def projects_retire(args):
    return _run(args, retired=True)


def projects_unretire(args):
    return _run(args, retired=False)
