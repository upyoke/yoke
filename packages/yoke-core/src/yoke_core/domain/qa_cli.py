"""QA CLI parser and dispatcher."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file
from yoke_core.domain.qa_execution import (
    cmd_artifact_add,
    cmd_artifact_list,
    cmd_run_add,
    cmd_run_add_batch,
    cmd_run_complete,
    cmd_run_get,
    cmd_run_list,
    cmd_satisfy_screenshot_evidence,
)
from yoke_core.domain.qa_gate_summary import dispatch_from_args as _gs_dispatch, register_subparser as _register_gate_summary
from yoke_core.domain import qa_requirement_policy_validation as _qap
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m yoke_core.domain.qa", description="QA domain CRUD")
    sub = p.add_subparsers(dest="subcmd")

    sub.add_parser("init")

    ra = sub.add_parser("requirement-add")
    ra.add_argument("--item-id", type=int)
    ra.add_argument("--epic-id", type=int)
    ra.add_argument("--task-num", type=int)
    ra.add_argument("--deployment-run-id")
    ra.add_argument("--qa-kind", required=True, help=_qap.QA_KIND_HELP)
    ra.add_argument("--qa-phase", required=True)
    ra.add_argument("--target-env")
    ra.add_argument("--blocking-mode", default="blocking")
    ra.add_argument(
        "--requirement-source", choices=_qap.VALID_REQUIREMENT_SOURCES,
        default="explicit", help=_qap.REQUIREMENT_SOURCE_HELP,
    )
    ra.add_argument("--success-policy", help=_qap.SUCCESS_POLICY_HELP)
    ra.add_argument("--capability-requirements")
    ra.add_argument("--suite-id")

    rab = sub.add_parser("requirement-add-batch")
    rab.add_argument("--json-file", required=True, help="Path to JSON array of requirement objects")

    rl = sub.add_parser("requirement-list")
    rl.add_argument("--item-id", type=int)
    rl.add_argument("--epic-id", type=int)
    rl.add_argument("--deployment-run-id")

    rg = sub.add_parser("requirement-get")
    rg.add_argument("id", type=int)

    ru = sub.add_parser(
        "requirement-update",
        help="Update a mutable field on an existing QA requirement.",
    )
    ru.add_argument("id", type=int)
    ru.add_argument(
        "field",
        help=(
            "Field to update. Allowed: success_policy, blocking_mode, target_env, "
            "capability_requirements, suite_id, qa_phase. qa_kind is NOT updatable; "
            "use requirement-waive + requirement-add to change the verification surface."
        ),
    )
    ru_value = ru.add_mutually_exclusive_group()
    ru_value.add_argument(
        "value",
        nargs="?",
        help="Literal value to write. Use --stdin or --body-file for JSON or multi-line values.",
    )
    ru_value.add_argument(
        "--stdin",
        action="store_true",
        help="Read the value from standard input (preferred for success_policy JSON).",
    )
    ru_value.add_argument(
        "--body-file",
        help="Read the value from a file.",
    )

    rw = sub.add_parser("requirement-waive")
    rw.add_argument("id", type=int)
    rw.add_argument("rationale")
    rw.add_argument("--source", default="agent")
    rw.add_argument("--force", action="store_true")

    rna = sub.add_parser("run-add")
    rna.add_argument("--requirement-id", type=int, required=True)
    rna.add_argument("--executor-type", required=True)
    rna.add_argument(
        "--qa-kind",
        help=(
            "Optional. Defaults to the matching qa_requirements row's "
            "qa_kind; supplying a different value is a hard error."
        ),
    )
    rna.add_argument("--verdict")
    rna.add_argument(
        "--execution-status",
        choices=("captured", "capture_failed"),
        help="Browser capture outcome, distinct from quality verdict.",
    )
    rna.add_argument("--score", type=float)
    rna.add_argument("--confidence", type=float)
    rna_raw = rna.add_mutually_exclusive_group()
    add_text_file_pair(rna_raw, "--raw-result", "--raw-result-file", dest="raw_result")
    rna.add_argument("--duration-ms", type=int)
    rna.add_argument(
        "--artifact-path",
        help=(
            "Optional screenshot path; creates a linked qa_artifact automatically "
            "and canonicalizes item-backed files into scratch-backed QA storage."
        ),
    )

    rnab = sub.add_parser("run-add-batch")
    rnab.add_argument("--json-file", required=True, help="Path to JSON array of run objects")

    rc = sub.add_parser("run-complete")
    rc.add_argument("--run-id", type=int, required=True)
    rc.add_argument("--verdict")
    rc.add_argument(
        "--execution-status",
        choices=("captured", "capture_failed"),
        help="Browser capture outcome, distinct from quality verdict.",
    )
    rc_raw = rc.add_mutually_exclusive_group()
    add_text_file_pair(rc_raw, "--raw-result", "--raw-result-file", dest="raw_result")
    rc.add_argument("--duration-ms", type=int)

    rnl = sub.add_parser("run-list")
    rnl.add_argument("--requirement-id", type=int)

    rng = sub.add_parser("run-get")
    rng.add_argument("id", type=int)

    aa = sub.add_parser("artifact-add")
    aa.add_argument("--run-id", type=int)
    aa.add_argument("--artifact-type", required=True)
    aa.add_argument("--content-type")
    aa.add_argument("--artifact-handle", help='Typed handle JSON ({"backend":"s3"|"local",...}); bare paths are refused.')
    aa.add_argument("--metadata")

    # artifact-list
    al = sub.add_parser("artifact-list")
    al.add_argument("--run-id", type=int)
    al.add_argument("--item-id", type=int, help="List all artifacts for an item (joins through runs/requirements)")
    al.add_argument("--resolve-addresses", action="store_true", help="Resolve handles honestly: filesystem path (local), s3://bucket/key URI (s3).")

    # baseline-record
    br = sub.add_parser("baseline-record")
    br.add_argument("--route", required=True)
    br.add_argument("--width", type=int, required=True)
    br.add_argument("--height", type=int, required=True)
    br.add_argument("--branch", default="")
    br.add_argument("--commit", default="")
    br.add_argument("--project")
    br.add_argument("--screenshot-path", required=True)
    br.add_argument("--update", action="store_true")

    # baseline-list
    bl = sub.add_parser("baseline-list")
    bl.add_argument("--project")

    # baseline-get
    bg = sub.add_parser("baseline-get")
    bg.add_argument("route")
    bg.add_argument("viewport")

    # baseline-promote
    bp = sub.add_parser("baseline-promote")
    bp.add_argument("id", type=int)

    # satisfy-screenshot-evidence
    ss = sub.add_parser("satisfy-screenshot-evidence")
    ss.add_argument("--item-id", type=int, required=True)
    ss.add_argument("--evidence", default="Browser QA screenshot evaluation passed -- screenshots consistent with acceptance criteria")

    _register_gate_summary(sub)

    return p


# Public alias matching the contract documented in Task 002.
build_parser = _build_parser


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
        cmd_requirement_waive(args.id, args.rationale, db_path=db_path, source=args.source, force=args.force)
    elif args.subcmd == "run-add":
        try:
            raw_result = resolve_text_file(args.raw_result, args.raw_result_file, "--raw-result-file")
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
            raw_result = resolve_text_file(args.raw_result, args.raw_result_file, "--raw-result-file")
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
    elif args.subcmd == "satisfy-screenshot-evidence":
        cmd_satisfy_screenshot_evidence(
            db_path=db_path,
            item_id=args.item_id,
            evidence=args.evidence,
        )
    elif args.subcmd == "gate-summary":
        sys.exit(_gs_dispatch(args, db_path))
