"""Dash filing, survey, evidence, and escalation adapters."""

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
from yoke_contracts.dash_evidence_status import status_argument_kwargs
from yoke_cli.commands.adapters.dash_verification_plan import (
    DashVerificationPlanError,
    resolve_dash_verification_plan,
)
from yoke_cli.commands.adapters.dash_survey_recovery import (
    build_survey_timeout_recovery,
)
from yoke_cli.commands.adapters.file_line_sizing import survey_path_sizes
from yoke_cli.commands.adapters.lane_tree import item_lane_tree, verification_tree

DASH_FILE_USAGE = (
    "yoke dash TITLE INSTRUCTION --execution-instructions-considered "
    "[--project P] [--priority P] "
    "[--verification-plan ID_OR_SLUG | --verification-method ID] [--path-claims] "
    "[--approval-on-done] [--deployment] [--session-id S] [--json]"
)
DASH_SURVEY_USAGE = (
    "yoke direct-workflow dash survey ITEM "
    "(--path PATH [--path PATH ...] | --no-changes) "
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
    verification.add_argument("--verification-plan", metavar="ID_OR_SLUG")
    verification.add_argument("--verification-method")
    parser.add_argument("--path-claims", action="store_true")
    parser.add_argument("--approval-on-done", action="store_true")
    parser.add_argument("--deployment", action="store_true")
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
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--path", dest="paths", action="append")
    scope.add_argument("--no-changes", action="store_true")
    parser.add_argument("--integration-target", default="main")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DASH_SURVEY_USAGE)
    if parsed is None:
        return 2
    paths = parsed.paths or []
    # Size the item's tree, not whatever checkout this command runs from.
    # A live lane is the tree being changed; before a lane exists, the
    # item project's machine-mapped checkout is the tree — caller cwd is
    # the wrong repo for a cross-project item.
    path_sizes = []
    if paths:
        lane = item_lane_tree(parsed.item, parsed.project, parsed.session_id)
        tree_root = lane.path if lane.live else (lane.checkout or None)
        try:
            path_sizes = survey_path_sizes(paths, tree_root=tree_root)
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

    target = item_target("item", parsed.item, parsed.project)
    payload = {
        "paths": paths,
        "integration_target": parsed.integration_target,
        "path_sizes": path_sizes,
        "no_changes": parsed.no_changes,
    }
    return dispatch_and_emit(
        function_id="direct_workflow.dash.survey",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human,
        response_recovery=build_survey_timeout_recovery(target, payload),
    )


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
    parser.add_argument("--verification-status", **status_argument_kwargs())
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--path", dest="paths", action="append", default=[])
    parser.add_argument("--posture-check", action="append", default=[])
    parser.add_argument("--no-changes", action="store_true")
    parser.add_argument(
        "--tree-root",
        default="",
        help="Verification tree root. Defaults to the item's recorded "
        "implementation lane.",
    )
    parser.add_argument(
        "--tree-head-sha",
        default="",
        help="HEAD sha of the verification tree. Defaults to --commit-sha, "
        "the lane head this evidence records.",
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
    # A caller who named both halves has already answered; skip the lookup.
    lane_path = ""
    if not (parsed.tree_root and parsed.tree_head_sha):
        lane_path = item_lane_tree(
            parsed.item, parsed.project, parsed.session_id,
        ).path
    tree_root, tree_head_sha = verification_tree(
        parsed.tree_root,
        parsed.tree_head_sha,
        lane_path=lane_path,
        commit_sha=parsed.commit_sha,
    )
    if not tree_root or not tree_head_sha:
        return usage_error(
            "could not resolve the verification tree: this item has no "
            "recorded implementation lane and this directory is not a git "
            "worktree; pass --tree-root and --tree-head-sha."
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


__all__ = [
    "DASH_EVIDENCE_USAGE",
    "DASH_ESCALATE_USAGE",
    "DASH_FILE_USAGE",
    "DASH_PRIORITY_CHOICES",
    "DASH_SURVEY_USAGE",
    "dash_escalate",
    "dash_evidence",
    "dash_file",
    "dash_survey",
]
