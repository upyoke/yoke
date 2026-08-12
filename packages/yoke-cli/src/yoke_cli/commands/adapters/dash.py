"""Dash filing, survey, evidence, escalation, and field-note adapters."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.adapters.file_line_sizing import survey_path_sizes

DASH_FILE_USAGE = (
    "yoke dash TITLE INSTRUCTION [--project P] [--priority P] "
    "[--verification-plan ID | --verification-method ID] [--path-claims] "
    "[--approval-on-done] [--deployment] [--session-id S] [--json]"
)
DASH_SURVEY_USAGE = (
    "yoke direct-workflow dash survey ITEM --path PATH [--path PATH ...] "
    "[--integration-target BRANCH] [--project P] [--session-id S] [--json]"
)
DASH_EVIDENCE_USAGE = (
    "yoke direct-workflow dash evidence ITEM --result TEXT "
    "--verification TEXT --commit-sha SHA --merge-sha SHA "
    "[--path PATH ... | --no-changes] [--posture-check KEY=STATUS ...] "
    "[--tree-root PATH] [--tree-head-sha SHA] "
    "[--project P] [--session-id S] [--json]"
)
DASH_ESCALATE_USAGE = (
    "yoke direct-workflow dash escalate ITEM --issue-title TITLE "
    "--findings TEXT [--priority P] [--project P] [--session-id S] [--json]"
)
FIELD_NOTE_PROMOTE_USAGE = (
    "yoke ouroboros field-note promote ENTRY --title TITLE "
    "[--instruction TEXT] [--project P] [--priority P] "
    "[--session-id S] [--json]"
)

# Parse-time filing choices; stored priority semantics stay in the domain.
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
    verification.add_argument("--verification-plan", type=int)
    verification.add_argument("--verification-method")
    parser.add_argument("--path-claims", action="store_true")
    parser.add_argument("--approval-on-done", action="store_true")
    parser.add_argument("--deployment", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DASH_FILE_USAGE)
    if parsed is None:
        return 2
    posture: Dict[str, Any] = {}
    if parsed.verification_plan is not None:
        posture["verification"] = {
            "kind": "plan", "plan_id": parsed.verification_plan,
        }
    if parsed.verification_method:
        posture["verification"] = {
            "kind": "ad_hoc", "method_id": parsed.verification_method,
        }
    for key in ("path_claims", "approval_on_done", "deployment"):
        if getattr(parsed, key):
            posture[key] = True
    project = client_project_context(parsed.project)
    payload: Dict[str, Any] = {
        "title": parsed.title,
        "instruction": parsed.instruction,
        "workflow": "dash",
        "entry_surface": "cli",
        "workflow_posture": posture,
    }
    if project is not None:
        payload["project"] = project
    if parsed.priority:
        payload["priority"] = parsed.priority
    return dispatch_and_emit(
        function_id="items.create",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _item_parser(prog: str, usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("item")
    parser.add_argument("--project")
    return parser


def dash_survey(args: List[str]) -> int:
    parser = _item_parser(
        "yoke direct-workflow dash survey", DASH_SURVEY_USAGE,
    )
    parser.add_argument("--path", dest="paths", action="append", required=True)
    parser.add_argument("--integration-target", default="main")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DASH_SURVEY_USAGE)
    if parsed is None:
        return 2
    try:
        path_sizes = survey_path_sizes(parsed.paths)
    except RuntimeError as exc:
        return usage_error(str(exc))

    def _human(response, stdout, stderr) -> None:
        result = response.result or {}
        if result.get("clear"):
            print(f"survey-clear|{result.get('fingerprint') or ''}", file=stdout)
        print(
            f"survey-touch-path-update|{result.get('touch_path_update') or ''}",
            file=stdout,
        )
        for size in result.get("path_sizes") or []:
            print(
                "survey-size|"
                + "|".join(str(size.get(key)) for key in (
                    "path", "current_line_count", "remaining_headroom",
                    "at_or_over_limit", "limit", "classification",
                )),
                file=stdout,
            )
        for blocker in result.get("blockers") or []:
            print(
                "survey-blocked|"
                + "|".join(
                    str(blocker.get(key) or "")
                    for key in ("kind", "owner_item_id", "path", "state", "detail")
                ),
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="direct_workflow.dash.survey",
        target=item_target("item", parsed.item, parsed.project),
        payload={
            "paths": parsed.paths,
            "integration_target": parsed.integration_target,
            "path_sizes": path_sizes,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human,
    )


def _verification_tree(
    root_override: str, head_override: str,
) -> tuple[str, str]:
    """Resolve the tree this evidence describes, honouring overrides.

    Both halves come from the local checkout, so the client answers them
    rather than the dispatcher — a hosted server has no worktree to
    inspect. The engine-side resolver is reached through the sanctioned
    dynamic-import lane, for the same reason session orientation is: the
    client cannot take static authority over engine modules before the
    transport decision. Absent engine, or a directory with no git
    metadata, leaves the halves empty and the caller asks for them
    explicitly.
    """
    import importlib

    root = str(root_override).strip()
    head = str(head_override).strip()
    if root and head:
        return root, head
    try:
        module = importlib.import_module(
            "yoke_core.domain.verification_tree_binding"
        )
        identity = module.resolve_tree_identity()
    except Exception:
        identity = None
    if identity is None:
        return root, head
    return root or identity.root, head or identity.head_sha


def _posture_checks(values: List[str]) -> Dict[str, str]:
    checks: Dict[str, str] = {}
    for value in values:
        key, separator, outcome = value.partition("=")
        if not separator or not key.strip() or not outcome.strip():
            raise ValueError("--posture-check requires KEY=STATUS")
        checks[key.strip()] = outcome.strip()
    return checks


def dash_evidence(args: List[str]) -> int:
    parser = _item_parser(
        "yoke direct-workflow dash evidence", DASH_EVIDENCE_USAGE,
    )
    parser.add_argument("--result", required=True)
    parser.add_argument("--verification", required=True)
    parser.add_argument("--verification-status", default="passed")
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--path", dest="paths", action="append", default=[])
    parser.add_argument("--posture-check", action="append", default=[])
    parser.add_argument("--no-changes", action="store_true")
    parser.add_argument(
        "--tree-root",
        default="",
        help="Verification tree root. Defaults to this directory's git "
        "worktree root.",
    )
    parser.add_argument(
        "--tree-head-sha",
        default="",
        help="HEAD sha of the verification tree. Defaults to the resolved "
        "tree's HEAD.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DASH_EVIDENCE_USAGE)
    if parsed is None:
        return 2
    try:
        checks = _posture_checks(parsed.posture_check)
    except ValueError as exc:
        return usage_error(str(exc))
    tree_root, tree_head_sha = _verification_tree(
        parsed.tree_root, parsed.tree_head_sha,
    )
    if not tree_root or not tree_head_sha:
        return usage_error(
            "could not resolve the verification tree from this directory; "
            "run from the tree the verification covered, or pass "
            "--tree-root and --tree-head-sha."
        )
    return dispatch_and_emit(
        function_id="direct_workflow.dash.evidence",
        target=item_target("item", parsed.item, parsed.project),
        payload={
            "result_summary": parsed.result,
            "verification_summary": parsed.verification,
            "verification_status": parsed.verification_status,
            "commit_sha": parsed.commit_sha,
            "merge_sha": parsed.merge_sha,
            "touched_files": parsed.paths,
            "posture_checks": checks,
            "no_changes": parsed.no_changes,
            "tree_root": tree_root,
            "tree_head_sha": tree_head_sha,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def dash_escalate(args: List[str]) -> int:
    parser = _item_parser(
        "yoke direct-workflow dash escalate", DASH_ESCALATE_USAGE,
    )
    parser.add_argument("--issue-title", required=True)
    parser.add_argument("--findings", required=True)
    parser.add_argument("--priority")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DASH_ESCALATE_USAGE)
    if parsed is None:
        return 2
    payload = {
        "issue_title": parsed.issue_title,
        "findings": parsed.findings,
    }
    if parsed.priority:
        payload["priority"] = parsed.priority
    return dispatch_and_emit(
        function_id="direct_workflow.dash.escalate",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def field_note_promote(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros field-note promote",
        description=FIELD_NOTE_PROMOTE_USAGE,
    )
    parser.add_argument("entry", type=int)
    parser.add_argument("--title", required=True)
    parser.add_argument("--instruction")
    parser.add_argument("--project")
    parser.add_argument("--priority")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, FIELD_NOTE_PROMOTE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "entry_id": parsed.entry,
        "title": parsed.title,
    }
    for key in ("instruction", "project", "priority"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value
    return dispatch_and_emit(
        function_id="ouroboros.field_note.promote",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "DASH_EVIDENCE_USAGE",
    "DASH_ESCALATE_USAGE",
    "DASH_FILE_USAGE",
    "DASH_PRIORITY_CHOICES",
    "DASH_SURVEY_USAGE",
    "FIELD_NOTE_PROMOTE_USAGE",
    "dash_escalate",
    "dash_evidence",
    "dash_file",
    "dash_survey",
    "field_note_promote",
]
