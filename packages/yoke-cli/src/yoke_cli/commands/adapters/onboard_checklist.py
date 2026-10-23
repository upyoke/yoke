"""Adapter for ``yoke onboard checklist``."""

from __future__ import annotations

import argparse
import sys
from typing import Any, List

from yoke_cli.commands._helpers import (
    client_project_context,
    parse_or_usage_error,
)
from yoke_cli.config import onboard_checklist_render, onboard_setup_facts
from yoke_cli.commands.adapters.onboard_checklist_get import get_setup, render_lookup
from yoke_cli.config.onboard_checklist_schema import (
    BRANCHES,
    CHECKLIST_STATUSES,
    ROW_IDS,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef

ONBOARD_CHECKLIST_INIT_USAGE = (
    "yoke onboard checklist init [--config PATH] [--checkout PATH] "
    "[--project P] [--project-id N] [--json] "
    "(without --config, both --project and --checkout are required)"
)
ONBOARD_CHECKLIST_USAGE = (
    "yoke onboard checklist [--run-id RUN] [--branch MODE] [--json] "
    "[--project-root PATH] [--project-id N] "
    "[--project P] [--config PATH] [--profile-file FILE] "
    "[--github-repo OWNER/REPO] [--row-status ROW=STATUS] "
    "[--evidence ROW=TEXT] [--blocker ROW=TEXT] [--note ROW=TEXT] "
    "[--view-path PATH | --no-view]"
)

_CONFIG_HELP = "Machine config file to use; default: the standard one."
_PROJECT_ID_HELP = "Numeric project id."


def onboard_checklist_cmd(args: List[str]) -> int:
    if args and args[0] == "init":
        return _init(args[1:])
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke onboard checklist",
    )
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parser.add_argument("--run-id", default=None, help="Setup run to resume.")
    parser.add_argument(
        "--project", default=None, help="Resume only this project's setup."
    )
    parser.add_argument("--config", dest="config_path", default=None, help=_CONFIG_HELP)
    parser.add_argument(
        "--profile-file",
        default=None,
        help="Save an already confirmed profile JSON object.",
    )
    parser.add_argument(
        "--branch",
        choices=BRANCHES,
        default=None,
        help="Setup path to follow.",
    )
    parser.add_argument(
        "--project-root", default=None, help="Project checkout the setup is for."
    )
    parser.add_argument("--project-id", type=int, default=None, help=_PROJECT_ID_HELP)
    parser.add_argument("--github-repo", default=None, help="Repo as OWNER/REPO.")
    parser.add_argument(
        "--row-status",
        action="append",
        default=[],
        help="Set a row's status as ROW=STATUS; repeatable.",
    )
    for flag in ("evidence", "blocker", "note"):
        parser.add_argument(
            f"--{flag}",
            action="append",
            default=[],
            help=f"Record a row's {flag} as ROW=TEXT; repeatable.",
        )
    view = parser.add_mutually_exclusive_group()
    view.add_argument(
        "--view-path", default=None, help="Where to write the checklist view file."
    )
    view.add_argument("--no-view", action="store_true", help="Write no view file.")
    parsed = parse_or_usage_error(parser, args, ONBOARD_CHECKLIST_USAGE)
    if parsed is None:
        return 2
    from yoke_cli.config.project_onboard_support import machine_config_path

    with machine_config_path(parsed.config_path):
        try:
            payload = _run_payload(parsed)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        target = _target(parsed.project_id, project=parsed.project)
        response = get_setup(payload, target)
        if not response.success:
            return emit_response(response, json_mode=parsed.json_mode)
        writes = any(
            (
                parsed.row_status,
                parsed.evidence,
                parsed.blocker,
                parsed.note,
                parsed.profile_file,
                parsed.branch,
                parsed.github_repo,
            )
        )
        if writes:
            response = call_dispatcher(
                function_id="onboard.checklist.run",
                target=target,
                payload=payload,
                actor=build_actor(),
            )
        elif (response.result or {}).get("run") is None:
            return emit_response(
                response, json_mode=parsed.json_mode, human_writer=render_lookup
            )
        if response.success and not parsed.no_view:
            try:
                onboard_checklist_render.write_project_view(
                    response.result or {},
                    project_root=parsed.project_root,
                    view_path=parsed.view_path,
                )
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        return emit_response(
            response,
            json_mode=parsed.json_mode,
            human_writer=_render_run_human,
        )


def onboard_checklist_init(args: List[str]) -> int:
    return _init(args)


def _init(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke onboard checklist init",
    )
    parser.add_argument("--config", dest="config_path", default=None, help=_CONFIG_HELP)
    parser.add_argument(
        "--checkout", dest="checkout_path", default=None, help="Project checkout path."
    )
    parser.add_argument(
        "--project",
        dest="project",
        default=None,
        help="Project slug or numeric id (standalone init).",
    )
    parser.add_argument("--project-id", type=int, default=None, help=_PROJECT_ID_HELP)
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parsed = parse_or_usage_error(parser, args, ONBOARD_CHECKLIST_INIT_USAGE)
    if parsed is None:
        return 2
    from yoke_cli.config.project_onboard_support import machine_config_path

    with machine_config_path(parsed.config_path):
        if parsed.project_id is not None and parsed.project_id <= 0:
            print("error: --project-id must be a positive integer", file=sys.stderr)
            return 1
        if parsed.config_path is None and not (
            (parsed.project or parsed.project_id is not None) and parsed.checkout_path
        ):
            print(
                "error: without --config, standalone init requires both "
                "--project (or --project-id) and --checkout",
                file=sys.stderr,
            )
            return 1
        payload: dict[str, Any] = {
            "machine_config_path": parsed.config_path,
            "checkout_path": parsed.checkout_path,
            "project_id": parsed.project_id,
        }
        if parsed.project:
            payload["project"] = parsed.project
        try:
            payload.update(
                onboard_setup_facts.collect(
                    config_path=parsed.config_path,
                    checkout_path=parsed.checkout_path,
                    project_id=parsed.project_id,
                )
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        response = get_setup(
            payload, _target(parsed.project_id, project=parsed.project)
        )
        if not response.success:
            return emit_response(response, json_mode=parsed.json_mode)
        response = call_dispatcher(
            function_id="onboard.checklist.init",
            target=_target(parsed.project_id, project=parsed.project),
            payload=payload,
            actor=build_actor(),
        )
        return emit_response(
            response,
            json_mode=parsed.json_mode,
            human_writer=_render_init_human,
        )


def _target(project_id: int | None, project: str | None = None) -> TargetRef:
    if project_id is not None:
        project_context: str | None = str(project_id)
    elif project:
        project_context = project
    else:
        project_context = client_project_context()
    return TargetRef(kind="global", project_id=project_context)


def _run_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": parsed.run_id,
        "branch": parsed.branch,
        "checkout_path": parsed.project_root,
        "project_root": parsed.project_root,
        "project_id": parsed.project_id,
        "project": parsed.project,
        "github_repo": parsed.github_repo,
        "row_status": _parse_assignments(
            parsed.row_status,
            "status",
            allowed_values=CHECKLIST_STATUSES,
        ),
        "evidence": _parse_assignments(parsed.evidence, "evidence"),
        "blocker": _parse_assignments(parsed.blocker, "blocker"),
        "note": _parse_assignments(parsed.note, "note"),
    }
    payload.update(
        onboard_setup_facts.collect(
            config_path=parsed.config_path,
            checkout_path=parsed.project_root,
            project_id=parsed.project_id,
        )
    )
    if parsed.profile_file:
        payload["metadata"] = {
            "execution_profile": onboard_setup_facts.read_profile(parsed.profile_file)
        }
    return {key: value for key, value in payload.items() if value not in (None, {}, [])}


def _parse_assignments(
    values: list[str],
    label: str,
    *,
    allowed_values: tuple[str, ...] | None = None,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"{label} must use ROW=VALUE: {raw}")
        row_id, value = raw.split("=", 1)
        row_id = row_id.strip()
        if row_id not in ROW_IDS:
            raise ValueError(
                f"unknown checklist row {row_id!r}; expected one of {', '.join(ROW_IDS)}"
            )
        selected = value.strip()
        if allowed_values is not None and selected not in allowed_values:
            raise ValueError(
                f"invalid status {selected!r}; expected one of {', '.join(allowed_values)}"
            )
        parsed[row_id] = selected
    return parsed


def _render_run_human(response: FunctionCallResponse, stdout, stderr) -> None:
    print(
        onboard_checklist_render.render_human(response.result or {}),
        end="",
        file=stdout,
    )


def _render_init_human(response: FunctionCallResponse, stdout, stderr) -> None:
    from yoke_cli.config.setup_facts_summary import summary_lines

    payload = response.result or {}
    lines = [
        "Yoke onboarding checklist",
        f"  config: {payload.get('machine_config_path')}",
        f"  checkout: {payload.get('checkout_path')}",
        f"  project_id: {payload.get('project_id')}",
        "",
        *summary_lines(payload),
        "",
    ]
    print("\n".join(lines), file=stdout)


__all__ = [
    "ONBOARD_CHECKLIST_INIT_USAGE",
    "ONBOARD_CHECKLIST_USAGE",
    "onboard_checklist_cmd",
    "onboard_checklist_init",
]
