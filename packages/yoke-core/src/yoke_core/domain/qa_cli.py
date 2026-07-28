"""QA CLI dispatcher."""

from __future__ import annotations

import os
import sys
from typing import Optional, Sequence

from yoke_core.domain import qa_requirement_policy_validation as _qap
from yoke_core.domain.cli_text_file import resolve_text_file
from yoke_core.domain.qa_cli_parser import build_parser
from yoke_core.domain.qa_execution import (
    cmd_artifact_add,
    cmd_artifact_list,
    cmd_run_add,
    cmd_run_add_batch,
    cmd_run_complete,
    cmd_run_get,
    cmd_run_list,
)
from yoke_core.domain.qa_gate_summary import dispatch_from_args as _gs_dispatch
from yoke_core.domain.qa_reporting import (
    cmd_baseline_get,
    cmd_baseline_list,
    cmd_baseline_promote,
    cmd_baseline_record,
)
from yoke_core.domain.qa_requirements import (
    cmd_requirement_add,
    cmd_requirement_add_batch,
    cmd_requirement_get,
    cmd_requirement_list,
    cmd_requirement_update,
    cmd_requirement_waive,
)
from yoke_core.domain.qa_schema import cmd_init

_build_parser = build_parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    db_path = os.environ.get("YOKE_DB") or None
    if args.subcmd == "init":
        cmd_init(db_path=db_path)
    elif args.subcmd == "requirement-add":
        if (
            args.item_id is not None or args.epic_id is not None
        ) and not args.workflow_transition_id:
            parser.error("--workflow-transition is required for item/epic QA")
        policy_errors = _qap.validate_success_policy(args.qa_kind, args.success_policy)
        if policy_errors:
            parser.error("\n".join(policy_errors))
        cmd_requirement_add(
            db_path=db_path,
            item_id=args.item_id,
            epic_id=args.epic_id,
            task_num=args.task_num,
            deployment_run_id=args.deployment_run_id,
            qa_kind=args.qa_kind,
            qa_phase=args.qa_phase,
            target_env=args.target_env,
            blocking_mode=args.blocking_mode,
            requirement_source=args.requirement_source,
            success_policy=args.success_policy,
            capability_requirements=args.capability_requirements,
            suite_id=args.suite_id,
            workflow_transition_id=args.workflow_transition_id,
        )
    elif args.subcmd == "requirement-add-batch":
        cmd_requirement_add_batch(db_path=db_path, json_file=args.json_file)
    elif args.subcmd == "requirement-list":
        cmd_requirement_list(
            db_path=db_path,
            item_id=args.item_id,
            epic_id=args.epic_id,
            deployment_run_id=args.deployment_run_id,
        )
    elif args.subcmd == "requirement-get":
        cmd_requirement_get(args.id, db_path=db_path)
    elif args.subcmd == "requirement-update":
        if args.stdin:
            value = sys.stdin.read()
        elif args.body_file:
            try:
                with open(args.body_file, "r", encoding="utf-8") as fh:
                    value = fh.read()
            except OSError as exc:
                print(f"Error: cannot read --body-file: {exc}", file=sys.stderr)
                sys.exit(2)
        else:
            value = args.value
        cmd_requirement_update(args.id, args.field, value, db_path=db_path)
    elif args.subcmd == "requirement-waive":
        cmd_requirement_waive(
            args.id,
            args.rationale,
            db_path=db_path,
            source=args.source,
            force=args.force,
        )
    elif args.subcmd == "run-add":
        try:
            raw_result = resolve_text_file(
                args.raw_result, args.raw_result_file, "--raw-result-file"
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        cmd_run_add(
            db_path=db_path,
            requirement_id=args.requirement_id,
            executor_type=args.executor_type,
            qa_kind=args.qa_kind,
            verdict=args.verdict,
            execution_status=args.execution_status,
            score=args.score,
            confidence=args.confidence,
            raw_result=raw_result,
            duration_ms=args.duration_ms,
            artifact_path=args.artifact_path,
        )
    elif args.subcmd == "run-add-batch":
        cmd_run_add_batch(db_path=db_path, json_file=args.json_file)
    elif args.subcmd == "run-complete":
        try:
            raw_result = resolve_text_file(
                args.raw_result, args.raw_result_file, "--raw-result-file"
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(2)
        cmd_run_complete(
            db_path=db_path,
            run_id=args.run_id,
            verdict=args.verdict,
            execution_status=args.execution_status,
            raw_result=raw_result,
            duration_ms=args.duration_ms,
        )
    elif args.subcmd == "run-list":
        cmd_run_list(db_path=db_path, requirement_id=args.requirement_id)
    elif args.subcmd == "run-get":
        cmd_run_get(args.id, db_path=db_path)
    elif args.subcmd == "artifact-add":
        cmd_artifact_add(
            db_path=db_path,
            run_id=args.run_id,
            artifact_type=args.artifact_type,
            content_type=args.content_type,
            artifact_handle=args.artifact_handle,
            metadata=args.metadata,
        )
    elif args.subcmd == "artifact-list":
        cmd_artifact_list(
            db_path=db_path,
            run_id=args.run_id,
            item_id=getattr(args, "item_id", None),
            resolve_addresses=getattr(args, "resolve_addresses", False),
        )
    elif args.subcmd == "baseline-record":
        cmd_baseline_record(
            db_path=db_path,
            route=args.route,
            width=args.width,
            height=args.height,
            branch=args.branch,
            commit=args.commit,
            project=args.project,
            screenshot_path=args.screenshot_path,
            update=args.update,
        )
    elif args.subcmd == "baseline-list":
        cmd_baseline_list(db_path=db_path, project=args.project)
    elif args.subcmd == "baseline-get":
        cmd_baseline_get(args.route, args.viewport, db_path=db_path)
    elif args.subcmd == "baseline-promote":
        cmd_baseline_promote(args.id, db_path=db_path)
    elif args.subcmd == "gate-summary":
        sys.exit(_gs_dispatch(args, db_path))
