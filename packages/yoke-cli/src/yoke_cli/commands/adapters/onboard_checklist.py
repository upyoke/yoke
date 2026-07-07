"""Adapter for ``yoke onboard checklist``."""

from __future__ import annotations

import argparse
import sys
from typing import Any, List, Mapping

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    client_project_context,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.config import onboard_checklist_render
from yoke_cli.config.onboard_checklist_schema import (
    BRANCHES,
    CHECKLIST_STATUSES,
    ROW_IDS,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef

ONBOARD_CHECKLIST_INIT_USAGE = (
    "yoke onboard checklist init --config PATH [--checkout PATH] "
    "[--project-id N] [--json]"
)
ONBOARD_CHECKLIST_USAGE = (
    "yoke onboard checklist [--run-id RUN] [--branch MODE] [--json] "
    "[--project-root PATH] [--project-id N] [--project-slug SLUG] "
    "[--github-repo OWNER/REPO] [--row-status ROW=STATUS] "
    "[--evidence ROW=TEXT] [--blocker ROW=TEXT] [--note ROW=TEXT] "
    "[--view-path PATH | --no-view]"
)


def onboard_checklist_cmd(args: List[str]) -> int:
    if args and args[0] == "init":
        return _init(args[1:])
    parser = argparse.ArgumentParser(prog="yoke onboard checklist")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parser.add_argument("--run-id", dest="run_id", default=None)
    parser.add_argument(
        "--branch", choices=BRANCHES, default="local-checkout",
    )
    parser.add_argument("--project-root", dest="project_root", default=None)
    parser.add_argument("--project-id", dest="project_id", type=int, default=None)
    parser.add_argument("--project-slug", dest="project_slug", default=None)
    parser.add_argument("--github-repo", dest="github_repo", default=None)
    parser.add_argument(
        "--row-status", dest="row_status", action="append", default=[],
    )
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--view-path", dest="view_path", default=None)
    view.add_argument("--no-view", dest="no_view", action="store_true")
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, ONBOARD_CHECKLIST_USAGE)
    if parsed is None:
        return 2
    try:
        payload = _run_payload(parsed)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="onboard.checklist.run",
        target=_target(parsed.project_id),
        payload=payload,
        actor=build_actor(),
    )
    if response.success and not parsed.no_view:
        try:
            _write_project_view(
                response,
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
    parser = argparse.ArgumentParser(prog="yoke onboard checklist init")
    parser.add_argument("--config", dest="config_path", required=True)
    parser.add_argument("--checkout", dest="checkout_path", default=None)
    parser.add_argument("--project-id", dest="project_id", type=int, default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, ONBOARD_CHECKLIST_INIT_USAGE)
    if parsed is None:
        return 2
    if parsed.project_id is not None and parsed.project_id <= 0:
        print("error: --project-id must be a positive integer", file=sys.stderr)
        return 1
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="onboard.checklist.init",
        target=_target(parsed.project_id),
        payload={
            "machine_config_path": parsed.config_path,
            "checkout_path": parsed.checkout_path,
            "project_id": parsed.project_id,
        },
        actor=build_actor(),
    )
    return emit_response(
        response,
        json_mode=parsed.json_mode,
        human_writer=_render_init_human,
    )


def _target(project_id: int | None) -> TargetRef:
    project_context = (
        str(project_id) if project_id is not None else client_project_context()
    )
    return TargetRef(kind="global", project_id=project_context)


def _run_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": parsed.run_id,
        "branch": parsed.branch,
        "checkout_path": parsed.project_root,
        "project_root": parsed.project_root,
        "project_id": parsed.project_id,
        "project_slug": parsed.project_slug,
        "github_repo": parsed.github_repo,
        "row_status": _parse_assignments(
            parsed.row_status, "status", allowed_values=CHECKLIST_STATUSES,
        ),
        "evidence": _parse_assignments(parsed.evidence, "evidence"),
        "blocker": _parse_assignments(parsed.blocker, "blocker"),
        "note": _parse_assignments(parsed.note, "note"),
    }
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, {}, [])
    }


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


def _write_project_view(
    response: FunctionCallResponse,
    *,
    project_root: str | None,
    view_path: str | None,
) -> None:
    result = response.result or {}
    selected = result.get("view_path") or view_path
    resolved = onboard_checklist_render.resolve_view_path(project_root, selected)
    if resolved is None:
        return
    record = _record_for_render(result)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        onboard_checklist_render.render_markdown(record), encoding="utf-8"
    )
    result["view_path"] = str(resolved)


def _record_for_render(result: Mapping[str, Any]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    status = str(summary.get("status") or result.get("status") or "unknown")
    return {
        "run_id": result.get("run_id") or "unknown",
        "branch": result.get("branch") or "unknown",
        "doctor": {"status": status},
        "rows": list(result.get("rows") or []),
    }


def _render_run_human(response: FunctionCallResponse, stdout, stderr) -> None:
    print(
        onboard_checklist_render.render_human(response.result or {}),
        end="",
        file=stdout,
    )


def _render_init_human(response: FunctionCallResponse, stdout, stderr) -> None:
    payload = response.result or {}
    lines = [
        "Yoke onboarding checklist",
        f"  config: {payload.get('machine_config_path')}",
        f"  checkout: {payload.get('checkout_path')}",
        f"  project_id: {payload.get('project_id')}",
        "",
        "Next:",
        "  - yoke onboard project",
        "",
    ]
    print("\n".join(lines), file=stdout)


__all__ = [
    "ONBOARD_CHECKLIST_INIT_USAGE",
    "ONBOARD_CHECKLIST_USAGE",
    "onboard_checklist_cmd",
    "onboard_checklist_init",
]
